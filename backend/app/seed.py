"""Seed the database with SYNTHETIC data (no real prisoner data, ever).

    python -m app.seed [--reset] [--population 60] [--llm]

Demo users (local development only; passwords are fixed test values):"""
from __future__ import annotations

import argparse
import sys
from datetime import date
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


def seed(population: int = 60, reset: bool = False, use_llm: bool = False, verbose: bool = True) -> dict:
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
        u = User(email=email, name=name, role=role, jail=jail, district=district, hashed_password=hash_password(DEMO_PASSWORD))
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
    lawyer, lawyer2 = users["lawyer@nyayasetu.test"], users["lawyer2@nyayasetu.test"]
    persons: list[Person] = []
    for i, sp in enumerate(data["persons"]):
        demo = sp["scenario"] != "random"
        p = Person(canonical_name=sp["canonical_name"], relative_name_variants=[sp["relative_name"]], relation=sp["relation"],
                   gender=sp["gender"], dob=_d(sp["dob"]), jail=sp["jail"], district=sp["district"], state="Karnataka",
                   vulnerability=sp["vulnerability"], synthetic_truth_id=sp["truth_id"],
                   identifiers={"scenario": sp["scenario"], "expected_status": sp["expected_status"]},
                   assigned_lawyer_id=(lawyer.id if demo or (sp["district"] == "Bengaluru Urban" and i % 2 == 0)
                                       else lawyer2.id))
        db.add(p)
        db.flush()
        cases: dict[str, Case] = {}
        for c in sp["cases"]:
            case = Case(cnr=c["cnr"], case_numbers=[c["case_number"]], court=c["court"], district=c["district"],
                        state=c["state"], fir_number=c["fir_number"], police_station=c["police_station"],
                        fir_year=int(c["fir_number"].split("/")[-1]), status=c["status"], offence_date=_d(c["offence_date"]),
                        fir_date=_d(c.get("fir_date")), first_remand_date=_d(c.get("first_remand_date")),
                        charge_sheet_date=_d(c.get("charge_sheet_date")), bail_granted_date=_d(c.get("bail_granted_date")),
                        acquittal_date=_d(c.get("acquittal_date")), conviction_date=_d(c.get("conviction_date")),
                        facts_summary=c.get("facts"))
            case.persons.append(p)
            for ch in c["charges"]:
                case.charges.append(Charge(act=ch["act"], section=ch["section"], modifier=ch["modifier"],
                                           offence_date=_d(ch["offence_date"]), confidence=0.95))
            for h in c["hearings"]:
                case.hearings.append(Hearing(date=_d(h["date"]), next_date=_d(h["next_date"]), reason_text=h["reason_text"],
                                             outcome_text=h["reason_text"]))
            db.add(case)
            db.flush()
            cases[c["ref"]] = case
            attribute_hearings(db, case.hearings, use_llm=use_llm)
        for e in sp["custody_events"]:
            db.add(CustodyEvent(person_id=p.id, case_id=cases[e["case_ref"]].id if e["case_ref"] else None, type=e["type"],
                                start=_d(e["start"]), end=_d(e["end"]), jail=e["jail"], confidence=e["confidence"],
                                is_primary_source=e["is_primary_source"],
                                source={"document_id": "", "doc_type": e["doc_type"], "text": f"{e['type']} {e['start']}"}))
        for cv in sp["convictions"]:
            db.add(Conviction(person_id=p.id, case_id=cv["case_ref"], date=_d(cv["date"]), status=cv["status"],
                              offence=cv["offence"]))
        db.flush()
        for k, doc in enumerate(sp["documents"]):
            case = cases.get(doc["case_ref"]) if doc["case_ref"] else None
            ingest(db, doc["text"].encode("utf-8"), f"{doc['doc_type']}_{sp['truth_id']}_{k}.txt", users["jail@nyayasetu.test"],
                   p, case.id if case else None, use_llm=use_llm, store_file=False)
        persons.append(p)
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
    a = ap.parse_args()
    seed(a.population, a.reset, a.llm)
