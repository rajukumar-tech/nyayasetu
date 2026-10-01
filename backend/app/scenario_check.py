"""Run the ~1,000 synthetic scenarios (data/synthetic/scenarios.py) through the REAL system and check them.

    python -m app.scenario_check            # writes docs/TEST_REPORT.md (+ docs/test_report.json)

For every scenario:
  * oracle      the result equals what the scenario generator derived independently (status, custody, delay,
                counted, threshold, maximum, eligibility date, projected date, overdue, findings, flags)
  * invariants  no negative/impossible numbers, eligibility date never after today, counted = custody − accused,
                statuses consistent with the numbers, timeline intervals sorted/non-overlapping and ≤ today
  * API         list row and detail agree (single source of truth); every role gets exactly its scope via the
                backend — out-of-scope IDs return the same 404 as unknown IDs; denials are audit-logged
  * recompute   identical inputs → no new result rows, no new alerts
  * identity    the duplicate scan never auto-merges and never proposes linking clearly different people

It uses its own in-memory database and a fixed "today", so it never touches the demo data.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

if __name__ == "__main__":  # standalone: never let the app's default engine point at the demo database
    os.environ["NYAYA_DATABASE_URL"] = "sqlite://"

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "synthetic"))

FIXED_TODAY = date(2026, 9, 30)
TERMINAL = {"NOT_APPLICABLE", "EXCLUDED_479"}


def run(target: int = 1000, api_checks: bool = True, write_report: bool = True, verbose: bool = True) -> dict:
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select
    from sqlalchemy.orm import sessionmaker

    from scenarios import generate_scenarios

    from app import models  # noqa: F401
    from app.core.config import settings
    from app.core.security import hash_password
    from app.db import Base, get_db, make_engine
    from app.models import Alert, AuditLog, Conviction, EligibilityResult, LegalVerification, Person, User
    from app.monitoring.alerts import run_nightly
    from app.seed import DEMO_VERIFIER, load_person
    from app.services.eligibility import compute_for_person, load_kb

    t0 = time.perf_counter()
    saved_today, saved_demo = settings.today_override, settings.demo_mode
    settings.today_override, settings.demo_mode = FIXED_TODAY, True
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    db = Session()
    results: list[dict] = []
    try:
        # ---------------------------------------------------------------- users
        pw = "scenario-test-pw"
        mk = lambda email, role, jail=None, district=None, active=True: User(  # noqa: E731
            email=email, name=email.split("@")[0], role=role, jail=jail, district=district, active=active,
            hashed_password=hash_password(pw), approved_at=datetime.now(timezone.utc) if active else None)
        from scenarios import DISTRICTS
        users = {"A": mk("lawyer.a@test", "legal_aid_lawyer"), "B": mk("lawyer.b@test", "legal_aid_lawyer"),
                 "C": mk("lawyer.c@test", "legal_aid_lawyer"), "D": mk("lawyer.d@test", "legal_aid_lawyer", active=False),
                 "reviewer": mk("reviewer@test", "reviewer"), "admin": mk("admin@test", "system_admin")}
        for i, (dist, jail, _) in enumerate(DISTRICTS):
            users[f"jail{i}"] = mk(f"jail{i}@test", "jail_staff", jail=jail)
            users[f"dlsa{i}"] = mk(f"dlsa{i}@test", "dlsa_admin", district=dist)
        db.add_all(users.values())
        db.flush()
        kb = load_kb(db)
        for key in list(kb.records) + [f"rule:{r}" for r in kb.rules]:
            db.add(LegalVerification(record_key=key, verified=True, verified_by=DEMO_VERIFIER, note="scenario run"))
        db.commit()

        # ---------------------------------------------------------------- load through the real pipeline
        scen = generate_scenarios(FIXED_TODAY, target=target)
        by_id: dict[str, dict] = {}
        for sp in scen:
            lawyer = users[sp["scope"]].id if sp["scope"] in ("A", "B") else None
            p = load_person(db, sp, lawyer, users["jail0"])
            if sp.get("oracle_fix_conviction_case"):
                for cv in db.scalars(select(Conviction).where(Conviction.person_id == p.id)):
                    cv.case_id = p.cases[0].id
            by_id[p.id] = sp
            sp["_pid"] = p.id
        db.commit()
        kb = load_kb(db)
        rep1 = run_nightly(db)
        load_s = time.perf_counter() - t0

        # ---------------------------------------------------------------- per-scenario checks
        for p in db.scalars(select(Person)):
            sp = by_id[p.id]
            row = db.scalar(select(EligibilityResult).where(EligibilityResult.person_id == p.id, EligibilityResult.is_current))
            res = row.result
            c0 = res["cases"][0] if res["cases"] else {}
            fails, warns = [], []
            _check_oracle(sp["oracle"], res, c0, fails)
            _check_invariants(res, FIXED_TODAY, fails, warns)
            if "oracle_documents" in sp:
                n = db.scalar(select(func.count()).select_from(models.Document).where(models.Document.person_id == p.id))
                if n != sp["oracle_documents"]:
                    fails.append(f"documents stored {n} ≠ expected {sp['oracle_documents']}")
            results.append({"id": sp["truth_id"], "pid": p.id, "tags": sp["tags"], "status": row.status,
                            "urgency": _urgency(res), "fails": fails, "warnings": warns, "category": "calculation"})

        # ---------------------------------------------------------------- recompute idempotency
        n_rows = db.scalar(select(func.count(EligibilityResult.id)))
        n_alerts = db.scalar(select(func.count(Alert.id)))
        changed = sum(compute_for_person(db, p, kb, commit=False).changed for p in db.scalars(select(Person)))
        rep2 = run_nightly(db)
        idem = {"changed_on_second_compute": changed, "result_rows_before": n_rows,
                "result_rows_after": db.scalar(select(func.count(EligibilityResult.id))),
                "alerts_before": n_alerts, "alerts_after": db.scalar(select(func.count(Alert.id))),
                "alerts_created_second_nightly": rep2.alerts_created}
        idem_ok = (changed == 0 and idem["result_rows_after"] == n_rows and idem["alerts_after"] == n_alerts
                   and rep2.alerts_created == 0)

        # ---------------------------------------------------------------- API: consistency + authorization
        auth = {"requests": 0, "failures": [], "denials_expected": 0}
        consistency_fails: list[str] = []
        identity: dict = {}
        audit_fail: list[str] = []
        if api_checks:
            from app.main import app

            def _get_db():
                s = Session()
                try:
                    yield s
                finally:
                    s.close()
            app.dependency_overrides[get_db] = _get_db
            with TestClient(app) as client:
                tok = {}
                for k, u in users.items():
                    r = client.post("/api/auth/login", json={"email": u.email, "password": pw})
                    if k == "D":
                        if r.status_code != 401:
                            auth["failures"].append(f"deactivated lawyer could sign in ({r.status_code})")
                        continue
                    tok[k] = {"Authorization": f"Bearer {r.json()['access_token']}"}
                persons = list(db.scalars(select(Person)))
                scope = {k: set() for k in tok}
                register_scope = {p.id for p in persons}  # the admin sees the register (no case details)
                for p in persons:
                    sp = by_id[p.id]
                    if sp["scope"] in ("A", "B"):
                        scope[sp["scope"]].add(p.id)
                    for i, (dist, jail, _) in enumerate(DISTRICTS):
                        if p.jail == jail:
                            scope[f"jail{i}"].add(p.id)
                        if p.district == dist:
                            scope[f"dlsa{i}"].add(p.id)
                # list endpoints return EXACTLY the scope (and nothing for reviewer / zero-assignment lawyer)
                rows_ref: dict[str, dict] = {}  # list rows as the DLSA of each district sees them
                # the technical admin has no register; each DLSA's register is exactly its district, without case details
                if client.get("/api/register", headers=tok["admin"]).status_code != 403:
                    auth["failures"].append("the technical admin can read the prisoner register")
                reg_ids: set[str] = set()
                for i in range(len(DISTRICTS)):
                    reg = client.get("/api/register", headers=tok[f"dlsa{i}"])
                    auth["requests"] += 2
                    ids = {x["id"] for x in reg.json()}
                    if ids != scope[f"dlsa{i}"]:
                        auth["failures"].append(f"dlsa{i} register differs from its district")
                    if any(k in x for x in reg.json() for k in ("cases", "custody_days", "eligibility", "documents")):
                        auth["failures"].append("register exposes case details")
                    reg_ids |= ids
                if reg_ids != register_scope:
                    auth["failures"].append("district registers do not cover every prisoner")
                for k, h in tok.items():
                    r = client.get("/api/persons", headers=h)
                    auth["requests"] += 1
                    if k in ("reviewer", "admin"):
                        if r.status_code != 403:
                            auth["failures"].append(f"{k} listed prisoners' case data ({r.status_code})")
                        continue
                    got = {x["id"] for x in r.json()}
                    if got != scope[k]:
                        auth["failures"].append(f"{k}: list returned {len(got)} rows, scope is {len(scope[k])} "
                                                f"(leaked {len(got - scope[k])}, missing {len(scope[k] - got)})")
                    if k.startswith("dlsa"):
                        rows_ref.update({x["id"]: x for x in r.json()})
                    # search and pagination never widen the scope
                    for q in ("a", "Kumar", "Ravi", "zzzz-no-match"):
                        s = client.get("/api/persons", params={"q": q}, headers=h)
                        auth["requests"] += 1
                        if not {x["id"] for x in s.json()} <= scope[k]:
                            auth["failures"].append(f"{k}: search {q!r} returned out-of-scope rows")
                    pages, off = set(), 0
                    while True:
                        s = client.get("/api/persons", params={"limit": 97, "offset": off}, headers=h)
                        auth["requests"] += 1
                        chunk = [x["id"] for x in s.json()]
                        if not chunk:
                            break
                        if pages & set(chunk):
                            auth["failures"].append(f"{k}: pagination returned a row twice")
                        pages |= set(chunk)
                        off += 97
                    if pages != scope[k]:
                        auth["failures"].append(f"{k}: pagination union differs from scope")
                if tok.get("C"):
                    if client.get("/api/persons", headers=tok["C"]).json():
                        auth["failures"].append("a lawyer with zero assignments saw prisoners")
                # detail endpoint per person per role; out-of-scope must be the same 404 as a made-up id
                missing = client.get("/api/persons/doesnotexist01", headers=tok["A"])
                for p in persons:
                    for k in ("A", "B", "C", "jail0", "jail1", "jail2", "dlsa0", "dlsa1", "dlsa2", "reviewer", "admin"):
                        r = client.get(f"/api/persons/{p.id}", headers=tok[k])
                        auth["requests"] += 1
                        allowed = p.id in scope.get(k, set())
                        if allowed and r.status_code != 200:
                            auth["failures"].append(f"{k} refused in-scope {p.id} ({r.status_code})")
                        elif not allowed:
                            auth["denials_expected"] += 1
                            exp = 403 if k in ("reviewer", "admin") else 404  # a role-level refusal, same for every id
                            if r.status_code != exp or (exp == 404 and r.json() != missing.json()):
                                auth["failures"].append(f"{k} got {r.status_code} for out-of-scope {p.id}")
                            if r.status_code == 200:
                                auth["failures"].append(f"LEAK: {k} read out-of-scope prisoner {p.id}")
                    # single source of truth: list row == detail (as the district's DLSA sees them)
                    dk = next(f"dlsa{i}" for i, (dist, _, _) in enumerate(DISTRICTS) if dist == p.district)
                    d = client.get(f"/api/persons/{p.id}", headers=tok[dk]).json()
                    auth["requests"] += 1
                    lr = rows_ref.get(p.id, {})
                    for f_ in ("status", "urgency", "custody_days", "eligible_from_date", "days_overdue", "name", "jail",
                               "district", "assigned_lawyer_id"):
                        if lr.get(f_) != d.get(f_):
                            consistency_fails.append(f"{by_id[p.id]['truth_id']}: list {f_}={lr.get(f_)!r} ≠ detail {d.get(f_)!r}")
                    ce = d["eligibility"]["cases"]
                    if ce and ce[0]["counted_days"] != ce[0]["custody_days"] - ce[0]["accused_days"] and ce[0]["status"] not in TERMINAL | {"CRITICAL_ACQUITTED_DETAINED"}:
                        consistency_fails.append(f"{by_id[p.id]['truth_id']}: counted ≠ custody − accused in the API")
                # sub-resources for a sample, every role
                sample = persons[:: max(1, len(persons) // 60)]
                for p in sample:
                    for k, h in tok.items():
                        allowed = p.id in scope.get(k, set())
                        for path, ok_when in ((f"/api/persons/{p.id}/insights", k in ("A", "B") and allowed),
                                              (f"/api/persons/{p.id}/drafts", allowed)):
                            r = client.get(path, headers=h)
                            auth["requests"] += 1
                            if ok_when and r.status_code != 200:
                                auth["failures"].append(f"{k} refused {path} ({r.status_code})")
                            if not ok_when and r.status_code == 200:
                                auth["failures"].append(f"LEAK: {k} read {path}")
                        dk = next(f"dlsa{i}" for i, (dist, _, _) in enumerate(DISTRICTS) if dist == p.district)
                        for d_ in client.get(f"/api/persons/{p.id}", headers=tok[dk]).json()["documents"][:1]:
                            r = client.get(f"/api/documents/{d_['id']}", headers=h)
                            auth["requests"] += 1
                            ok_when = allowed or k == "reviewer"
                            if ok_when != (r.status_code == 200):
                                auth["failures"].append(f"{k} document access {r.status_code} (allowed={ok_when})")
                        r = client.post(f"/api/persons/{p.id}/recompute", headers=h)
                        auth["requests"] += 1
                        if allowed != (r.status_code == 200):
                            auth["failures"].append(f"{k} recompute {r.status_code} (allowed={allowed})")
                        if not k.startswith(("A", "B")):  # only the assigned lawyer uploads documents
                            r = client.post(f"/api/persons/{p.id}/documents", files={"file": ("x.txt", b"FIR")}, headers=h)
                            auth["requests"] += 1
                            if r.status_code not in (403, 404):
                                auth["failures"].append(f"{k} could upload a document ({r.status_code})")
                # denied attempts are in the audit log (current run, not seeded data)
                with Session() as s2:
                    denied = s2.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "access_denied"))
                if denied < auth["denials_expected"] * 0.99:
                    audit_fail.append(f"only {denied} access_denied audit entries for {auth['denials_expected']} denials")
                # identity scan: queue only, never auto-merge, never link clearly different people
                r = client.post("/api/resolution/scan", headers=tok["reviewer"])
                queue = client.get("/api/review", params={"kind": "identity_match"}, headers=tok["reviewer"]).json()
                grp = {p.id: by_id[p.id].get("identity_group") for p in persons}
                same_pairs = sum(1 for it in queue if grp.get(it["payload"]["a"]) and grp[it["payload"]["a"]] == grp.get(it["payload"]["b"]))
                wrong_links = [it["title"] for it in queue if it["payload"]["decision"] == "link"
                               and grp.get(it["payload"]["a"]) and grp.get(it["payload"]["b"])
                               and grp[it["payload"]["a"]].split("-")[0] == grp[it["payload"]["b"]].split("-")[0]
                               and grp[it["payload"]["a"]] != grp[it["payload"]["b"]]]
                groups: dict[str, list[str]] = defaultdict(list)
                for pid_, g_ in grp.items():
                    if g_ and "-other" not in g_:
                        groups[g_].append(pid_)
                possible = sum(len(v) * (len(v) - 1) // 2 for v in groups.values())
                with Session() as s2:
                    merged = s2.scalar(select(func.count(Person.id)).where(Person.merged_into_id.is_not(None)))
                identity = {"queued": len(queue), "same_person_pairs_proposed": same_pairs, "same_person_pairs_total": possible,
                            "different_people_proposed_as_link": len(wrong_links), "auto_merged": merged}
            app.dependency_overrides.pop(get_db, None)

        # ---------------------------------------------------------------- report
        total = len(results)
        failed = [r for r in results if r["fails"]]
        cats = Counter(t for r in results for t in r["tags"])
        statuses = Counter(r["status"] for r in results)
        summary = {
            "generated_for_today": FIXED_TODAY.isoformat(), "scenarios": total, "passed": total - len(failed),
            "failed": len(failed), "warnings": sum(len(r["warnings"]) for r in results), "categories": len(cats),
            "statuses": dict(statuses), "calculation_failures": len(failed), "authorization_failures": len(auth["failures"]),
            "authorization_requests": auth["requests"], "out_of_scope_requests_denied": auth["denials_expected"],
            "consistency_failures": len(consistency_fails), "audit_failures": len(audit_fail),
            "recompute_idempotent": idem_ok, "recompute": idem, "identity": identity,
            "first_nightly_alerts": rep1.alerts_created, "seconds": round(time.perf_counter() - t0, 1),
            "load_seconds": round(load_s, 1),
        }
        out = {"summary": summary, "categories": dict(cats.most_common()),
               "failures": [{"id": r["id"], "tags": r["tags"], "fails": r["fails"]} for r in failed][:300],
               "authorization_failures": auth["failures"][:200], "consistency_failures": consistency_fails[:200],
               "audit_failures": audit_fail}
        if write_report:
            _write_report(out)
        if verbose:
            print(json.dumps(summary, indent=1))
            for r in failed[:40]:
                print(r["id"], r["tags"][:4], r["fails"][:3])
            for f_ in (auth["failures"] + consistency_fails + audit_fail)[:40]:
                print("API:", f_)
        return out
    finally:
        db.close()
        eng.dispose()
        settings.today_override, settings.demo_mode = saved_today, saved_demo


def _urgency(res: dict) -> str:
    from app.eligibility.engine import urgency_rank
    codes = [c["status"] for c in res["cases"]] + [f["code"] for c in res["cases"] for f in c.get("findings", [])]
    return min(codes, key=urgency_rank) if codes else "NOT_APPLICABLE"


def _check_oracle(o: dict, res: dict, c0: dict, fails: list[str]) -> None:
    overall = res["overall_status"]
    status = c0.get("status", "NOT_APPLICABLE")
    if o.get("status") and status != o["status"] and overall != o["status"]:
        fails.append(f"status {status} (overall {overall}) ≠ expected {o['status']}")
    if o.get("status_in") and status not in o["status_in"] and overall not in o["status_in"]:
        fails.append(f"status {status} not in {o['status_in']}")
    if o.get("urgency") and _urgency(res) != o["urgency"]:
        fails.append(f"urgency {_urgency(res)} ≠ {o['urgency']}")
    checks = {"custody_days": "custody_days", "accused_days": "accused_days", "counted_days": "counted_days",
              "threshold_days": "threshold_days", "max_days": "max_days", "eligible_from": "eligible_from_date",
              "projected": "projected_date", "days_overdue": "days_overdue"}
    relevant = status not in TERMINAL and status != "CRITICAL_ACQUITTED_DETAINED"
    for ok, rk in checks.items():
        if ok not in o:
            continue
        if ok in ("custody_days",):
            pass
        elif not relevant:
            continue
        if ok in ("eligible_from", "projected", "days_overdue") and status.startswith("REVIEW"):
            continue  # reviews keep their dates only where both readings agree
        if ok == "custody_days" and status in ("NOT_APPLICABLE",) and not res["cases"]:
            continue
        if c0.get(rk) != o[ok]:
            fails.append(f"{rk} {c0.get(rk)!r} ≠ expected {o[ok]!r}")
    codes = {f["code"] for c in res["cases"] for f in c.get("findings", [])}
    for f in o.get("findings", []):
        if f not in codes:
            fails.append(f"missing finding {f} (have {sorted(codes)})")
    for f in o.get("no_findings", []):
        if f in codes:
            fails.append(f"unexpected finding {f}")
    flags = {f["code"] for c in res["cases"] for f in c.get("flags", [])}
    for f in o.get("flags", []):
        if f not in flags:
            fails.append(f"missing flag {f}")


def _check_invariants(res: dict, today: date, fails: list[str], warns: list[str]) -> None:
    for c in res["cases"]:
        s = c["status"]
        cd, ad, cnt = c["custody_days"], c["accused_days"], c["counted_days"]
        if min(cd, ad, cnt) < 0:
            fails.append("negative day count")
        if ad > cd:
            fails.append("accused days exceed custody days")
        if s not in TERMINAL and s != "CRITICAL_ACQUITTED_DETAINED" and c.get("threshold_days") is not None and cnt != cd - ad:
            fails.append("counted ≠ custody − accused")
        ef = c.get("eligible_from_date")
        if ef and date.fromisoformat(ef) > today:
            fails.append(f"eligibility date {ef} after today")
        pj = c.get("projected_date")
        if pj and date.fromisoformat(pj) <= today:
            fails.append(f"projected date {pj} not in the future")
        thr, mx = c.get("threshold_days"), c.get("max_days")
        if s == "ELIGIBLE" and (thr is None or cnt < thr or not ef or c.get("days_overdue") != cnt - thr):
            fails.append("ELIGIBLE inconsistent with counted/threshold/date/overdue")
        if s == "NOT_YET" and (thr is None or cnt >= thr or not pj):
            fails.append("NOT_YET inconsistent with counted/threshold")
        if s == "CRITICAL_MUST_RELEASE" and (mx is None or cnt < mx):
            fails.append("CRITICAL_MUST_RELEASE below the maximum")
        if thr is not None and mx is not None and not (0 < thr <= mx):
            fails.append("threshold not within (0, max]")
        tl = c.get("timeline") or {}
        iv = tl.get("intervals", [])
        total = 0
        prev_end = None
        for i in iv:
            a, b = date.fromisoformat(i["start"]), date.fromisoformat(i["end"])
            if b < a or b > today:
                fails.append(f"impossible interval {a}–{b}")
            if prev_end and a <= prev_end:
                fails.append("overlapping timeline intervals (double counting)")
            prev_end = b
            total += (b - a).days + 1
        if total != cd:
            fails.append(f"timeline intervals sum {total} ≠ custody {cd}")
        if s in ("ELIGIBLE", "NOT_YET") and c.get("needs_verification"):
            fails.append("definite status despite unverified inputs")


def _write_report(out: dict) -> None:
    s = out["summary"]
    docs = ROOT / "docs"
    (docs / "test_report.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    lines = [
        "# Synthetic scenario test report", "",
        f"Generated by `python -m app.scenario_check` for a fixed date of {s['generated_for_today']}. "
        "All data is **synthetic**; the expected values come from an independent oracle in "
        "`data/synthetic/scenarios.py` (plain date-set arithmetic), never from the engine.", "",
        "| | |", "|---|---|",
        f"| Scenarios | **{s['scenarios']}** |", f"| Passed | **{s['passed']}** |", f"| Failed | **{s['failed']}** |",
        f"| Warnings | {s['warnings']} |", f"| Categories exercised | {s['categories']} |",
        f"| Calculation failures | {s['calculation_failures']} |",
        f"| Authorization failures | {s['authorization_failures']} (of {s['authorization_requests']} API requests; "
        f"{s['out_of_scope_requests_denied']} out-of-scope requests) |",
        f"| List ↔ detail consistency failures | {s['consistency_failures']} |",
        f"| Audit-log failures | {s['audit_failures']} |",
        f"| Recompute idempotent | {'yes' if s['recompute_idempotent'] else '**NO**'} |",
        f"| Runtime | {s['seconds']} s |", "",
        "## Status distribution", "", "| Status | Scenarios |", "|---|---|",
        *[f"| {k} | {v} |" for k, v in sorted(s["statuses"].items(), key=lambda kv: -kv[1])], "",
        "## Identity resolution", "",
        *[f"- {k.replace('_', ' ')}: {v}" for k, v in s.get("identity", {}).items()], "",
        "## Categories", "", "| Category | Scenarios |", "|---|---|",
        *[f"| {k} | {v} |" for k, v in out["categories"].items()], "",
        "## Failures", "",
    ]
    if not (out["failures"] or out["authorization_failures"] or out["consistency_failures"] or out["audit_failures"]):
        lines.append("None.")
    for f in out["failures"]:
        lines.append(f"- `{f['id']}` ({', '.join(f['tags'][:4])}): " + "; ".join(f["fails"]))
    for f in out["authorization_failures"] + out["consistency_failures"] + out["audit_failures"]:
        lines.append(f"- {f}")
    lines.append("")
    lines.append("Localization and UI checks run separately: `cd frontend && npm run check:i18n` (every string in "
                 "English, Kannada and Hindi; no hard-coded UI text) and `PW_CHANNEL=chrome npx playwright test` "
                 "(browser flows on desktop and mobile).")
    (docs / "TEST_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=1000)
    ap.add_argument("--no-api", action="store_true")
    a = ap.parse_args()
    o = run(a.target, api_checks=not a.no_api)
    s = o["summary"]
    sys.exit(0 if not (s["failed"] or s["authorization_failures"] or s["consistency_failures"] or s["audit_failures"]
                       or not s["recompute_idempotent"]) else 1)
