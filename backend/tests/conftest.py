from __future__ import annotations

import os
from datetime import date, timedelta

import pytest

os.environ.setdefault("NYAYA_DATABASE_URL", "sqlite://")
os.environ.setdefault("NYAYA_JWT_SECRET", "test-secret")

from app.core.config import settings  # noqa: E402
from app.domain import (  # noqa: E402
    Attribution, Case, CaseStatus, Charge, ComputeContext, Conviction, ConvictionStatus,
    CustodyEvent, CustodyType, Hearing, Modifier, Person, SourceRef,
)
from app.legal_kb.kb import KnowledgeBase  # noqa: E402

TODAY = date(2026, 1, 15)


@pytest.fixture(scope="session")
def kb_raw() -> KnowledgeBase:
    """Knowledge base exactly as shipped (everything unverified)."""
    return KnowledgeBase.load(settings.legal_data_dir)


@pytest.fixture()
def kb() -> KnowledgeBase:
    """Knowledge base with every record and rule marked verified (test-only)."""
    k = KnowledgeBase.load(settings.legal_data_dir)
    for r in k.records.values():
        r.verified = True
    for r in k.rules.values():
        r.verified = True
        if r.name == "derivations":
            for d in r.data.values():
                d["verified"] = True
    for m in k.mappings:
        m.verified = True
    return k


@pytest.fixture()
def ctx() -> ComputeContext:
    return ComputeContext(today=TODAY, confidence_threshold=0.8)


def days_ago(n: int) -> date:
    return TODAY - timedelta(days=n)


def src(doc: str = "D1", text: str = "", doc_type: str = "remand_order") -> SourceRef:
    return SourceRef(doc, 1, 0, len(text), text, doc_type)


def charge(section: str = "379", act: str = "IPC", modifier: Modifier | None = None,
           offence_date: date | None = date(2023, 1, 1), **kw) -> Charge:
    return Charge(act=act, section=section, modifier=modifier, offence_date=offence_date, **kw)


def make_case(cid: str = "C1", charges: list[Charge] | None = None, status: CaseStatus = CaseStatus.TRIAL,
              hearings: list[Hearing] | None = None, **kw) -> Case:
    return Case(id=cid, status=status, charges=charges if charges is not None else [charge()],
                hearings=hearings or [], **kw)


def custody(start: date, end: date | None = None, case_id: str | None = "C1",
            type: CustodyType = CustodyType.JUDICIAL_CUSTODY, **kw) -> CustodyEvent:
    return CustodyEvent(type=type, start=start, end=end, case_id=case_id, **kw)


def make_person(cases: list[Case], events: list[CustodyEvent], convictions: list[Conviction] | None = None) -> Person:
    return Person(id="P1", name="Test Person", cases=cases, custody_events=events, convictions=convictions or [])


def hearing(d: date, nxt: date, attribution: Attribution, reason: str = "", confidence: float = 0.95,
            verified: bool = False) -> Hearing:
    return Hearing(date=d, next_date=nxt, reason_text=reason, attribution=attribution,
                   attribution_confidence=confidence, reviewer_verified=verified)


def conviction(case_id: str, status: ConvictionStatus, d: date = date(2019, 5, 1)) -> Conviction:
    return Conviction(case_id=case_id, date=d, status=status, offence="IPC 379")


@pytest.fixture()
def db():
    """Fresh in-memory database per test."""
    from sqlalchemy.orm import sessionmaker
    from app import models  # noqa: F401
    from app.db import Base, make_engine
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()
    eng.dispose()
