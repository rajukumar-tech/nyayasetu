"""Seed the database with SYNTHETIC data (no real prisoner data, ever).

    python -m app.seed [--reset] [--population 60] [--llm]

Demo users (local development only; passwords are fixed test values):"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.config import REPO_ROOT, settings
from app.core.security import hash_password
from app.db import Base, SessionLocal, engine
from app.delays.service import attribute_hearings
from app.defense.service import refresh_insights
from app.ingestion.pipeline import ingest
from app.models import (
    Case, Charge, Conviction, CustodyEvent, Hearing, LegalVerification, Person, User,
)
from app.monitoring.alerts import run_nightly
from app.services.eligibility import load_kb

DEMO_PASSWORD = "nyaya-demo-2026"  # test value for local demo accounts only
DEMO_USERS = [
    ("lawyer@nyayasetu.test", "Adv. Meera Rao (Legal Aid)", "legal_aid_lawyer", None, None),
    ("lawyer2@nyayasetu.test", "Adv. Farhan Ali (Legal Aid)", "legal_aid_lawyer", None, None),
    ("jail@nyayasetu.test", "Supdt. Office, Parappana Agrahara", "jail_staff", "Central Prison Parappana Agrahara", None),
    ("dlsa@nyayasetu.test", "DLSA Secretary, Bengaluru Urban", "dlsa_admin", None, "Bengaluru Urban"),
    ("reviewer@nyayasetu.test", "Law student reviewer", "reviewer", None, None),
    ("admin@nyayasetu.test", "System administrator", "system_admin", None, None),
]
DEMO_VERIFIER = "DEMO SEED — simulated verification for the demo only; NOT a legal check"


def _d(v: str | None) -> date | None:
    return date.fromisoformat(v) if v else None


def load_person(db, sp: dict, lawyer_id: str | None, uploader: User | None, use_llm: bool = False) -> Person:
    """Load one synthetic person (generator format) through the same paths real data takes: ORM rows, the delay
    classifier for hearings, and document ingestion/extraction for documents. Optional keys used by the test
    scenarios: hearing `attribution`/`verified` (a reviewer's decision), charge `confidence`, case
    `default_bail_application_date`, person `dob`/`relative_name` = None, `addresses`."""
    ident = {"scenario": sp["scenario"], "expected_status": sp.get("expected_status")}
    if sp.get("demo_label"):
        ident["demo_label"] = sp["demo_label"]
    p = Person(canonical_name=sp["canonical_name"],
               relative_name_variants=[sp["relative_name"]] if sp.get("relative_name") else [],
               relation=sp.get("relation"), gender=sp.get("gender"), dob=_d(sp.get("dob")), jail=sp.get("jail"),
               district=sp.get("district"), state="Karnataka", vulnerability=sp.get("vulnerability") or [],
               name_variants=sp.get("name_variants") or [], addresses=sp.get("addresses") or [],
               synthetic_truth_id=sp["truth_id"], identifiers=ident, assigned_lawyer_id=lawyer_id)
    db.add(p)
    db.flush()
    cases: dict[str, Case] = {}
    for c in sp["cases"]:
        fir_year = c["fir_number"].split("/")[-1] if c.get("fir_number") else ""
        case = Case(cnr=c.get("cnr"), case_numbers=[c["case_number"]] if c.get("case_number") else [], court=c.get("court"),
                    district=c.get("district"), state=c.get("state"), fir_number=c.get("fir_number"),
                    police_station=c.get("police_station"), fir_year=int(fir_year) if fir_year.isdigit() else None,
                    status=c["status"], offence_date=_d(c.get("offence_date")),
                    fir_date=_d(c.get("fir_date")), first_remand_date=_d(c.get("first_remand_date")),
                    charge_sheet_date=_d(c.get("charge_sheet_date")), bail_granted_date=_d(c.get("bail_granted_date")),
                    default_bail_application_date=_d(c.get("default_bail_application_date")),
                    acquittal_date=_d(c.get("acquittal_date")), conviction_date=_d(c.get("conviction_date")),
                    facts_summary=c.get("facts"))
        case.persons.append(p)
        for ch in c["charges"]:
            case.charges.append(Charge(act=ch["act"], section=ch["section"], modifier=ch.get("modifier"),
                                       offence_date=_d(ch.get("offence_date")), confidence=ch.get("confidence", 0.95)))
        for h in c["hearings"]:
            case.hearings.append(Hearing(date=_d(h["date"]), next_date=_d(h.get("next_date")), reason_text=h["reason_text"],
                                         outcome_text=h["reason_text"]))
        db.add(case)
        db.flush()
        cases[c["ref"]] = case
        attribute_hearings(db, case.hearings, use_llm=use_llm)
        for hrow, h in zip(_in_input_order(case.hearings, c["hearings"]), c["hearings"]):
            if h.get("attribution"):  # a reviewer already decided this adjournment
                hrow.delay_attribution, hrow.attribution_confidence = h["attribution"], 1.0
                hrow.attribution_method, hrow.reviewer_verified = "reviewer", bool(h.get("verified", True))
    for e in sp["custody_events"]:
        db.add(CustodyEvent(person_id=p.id, case_id=cases[e["case_ref"]].id if e.get("case_ref") else None, type=e["type"],
                            start=_d(e["start"]), end=_d(e.get("end")), jail=e.get("jail"), confidence=e.get("confidence", 0.95),
                            is_primary_source=e.get("is_primary_source", True),
                            source={"document_id": "", "doc_type": e.get("doc_type", "remand_order"),
                                    "text": f"{e['type']} {e['start']}"}))
    for cv in sp.get("convictions", []):
        db.add(Conviction(person_id=p.id, case_id=cv["case_ref"], date=_d(cv["date"]), status=cv["status"],
                          offence=cv.get("offence", "")))
    db.flush()
    for k, doc in enumerate(sp.get("documents", [])):
        case = cases.get(doc["case_ref"]) if doc.get("case_ref") else None
        ingest(db, doc["text"].encode("utf-8"), f"{doc['doc_type']}_{sp['truth_id']}_{k}.txt", uploader,
               p, case.id if case else None, use_llm=use_llm, store_file=False)
    return p


def _in_input_order(rows: list[Hearing], raw: list[dict]) -> list[Hearing]:
    """ORM hearings come back ordered by date; match them to the input list by (date, next_date, reason)."""
    pool = list(rows)
    out = []
    for h in raw:
        key = (_d(h["date"]), _d(h.get("next_date")), h["reason_text"])
        m = next(r for r in pool if (r.date, r.next_date, r.reason_text) == key)
        pool.remove(m)
        out.append(m)
    return out


def seed(population: int = 60, reset: bool = False, use_llm: bool = False, verbose: bool = True,
         full: bool = True) -> dict:
    """full=False loads ONLY the two headline demo prisoners (Ravi Kumar — not eligible, Suresh Kumar — eligible)."""
    sys.path.insert(0, str(REPO_ROOT / "data" / "synthetic"))
    from generate import generate  # noqa: E402

    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    if db.scalar(select(User.id)) is not None and not reset:
        print("Database already seeded (use --reset to rebuild).")
        return {}
    users = {}
    for email, name, role, jail, district in DEMO_USERS:
        u = User(email=email, name=name, role=role, jail=jail, district=district, hashed_password=hash_password(DEMO_PASSWORD),
                 approved_at=datetime.now(timezone.utc))
        db.add(u)
        users[email] = u
    db.flush()

    if settings.demo_mode:
        kb = load_kb(db)
        for key in list(kb.records) + [f"rule:{r}" for r in kb.rules]:
            db.add(LegalVerification(record_key=key, verified=True, verified_by=DEMO_VERIFIER,
                                     note="Demo mode. Replace with real verification against India Code / Gazette."))
        db.flush()

    data = generate(settings.today(), seed=7, population=population)
    if not full:
        data["persons"] = [sp for sp in data["persons"] if sp.get("demo_label")]
    lawyer, lawyer2 = users["lawyer@nyayasetu.test"], users["lawyer2@nyayasetu.test"]
    persons: list[Person] = []
    for i, sp in enumerate(data["persons"]):
        demo = sp["scenario"] != "random"
        lawyer_id = lawyer.id if demo or (sp["district"] == "Bengaluru Urban" and i % 2 == 0) else lawyer2.id
        persons.append(load_person(db, sp, lawyer_id, users["jail@nyayasetu.test"], use_llm))
    db.commit()
    kb = load_kb(db)
    rep = run_nightly(db)
    for p in persons:
        refresh_insights(db, p, kb)
    db.commit()
    summary = {"persons": len(persons), "alerts": rep.alerts_created, "demo_mode": settings.demo_mode}
    if verbose:
        print(f"Seeded {len(persons)} synthetic prisoners; {rep.alerts_created} alerts.")
        print(f"Demo logins (password '{DEMO_PASSWORD}'): " + ", ".join(u[0] for u in DEMO_USERS))
    db.close()
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--population", type=int, default=60)
    ap.add_argument("--llm", action="store_true", help="use the configured LLM during extraction (slower)")
    ap.add_argument("--full", action="store_true", help="also load the 10 edge-case showcase prisoners and the random "
                    "population (default: only the two headline demo prisoners)")
    a = ap.parse_args()
    seed(a.population, a.reset, a.llm, full=a.full)
