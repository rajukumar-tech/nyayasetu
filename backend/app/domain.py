"""Pure domain types shared by the deterministic engines.

These are plain dataclasses — no ORM, no I/O — so the timeline and eligibility
engines can be unit-tested exhaustively. `app.services.mapping` converts ORM
rows into these.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class CaseStatus(StrEnum):
    INVESTIGATION = "investigation"
    CHARGE_SHEET_FILED = "charge_sheet_filed"
    TRIAL = "trial"
    CONVICTED = "convicted"
    ACQUITTED = "acquitted"
    DISCHARGED = "discharged"
    DISPOSED = "disposed"

    @property
    def is_pending(self) -> bool:
        return self in (CaseStatus.INVESTIGATION, CaseStatus.CHARGE_SHEET_FILED, CaseStatus.TRIAL)


class CustodyType(StrEnum):
    # intervals that count as custody
    POLICE_CUSTODY = "police_custody"
    JUDICIAL_CUSTODY = "judicial_custody"
    HOSPITALISED_IN_CUSTODY = "hospitalised_in_custody"
    # point events that start custody
    ARREST = "arrest"
    RE_ARREST = "re_arrest"
    SURRENDERED = "surrendered"
    TRANSFER = "transfer"
    # point events that end custody
    RELEASED = "released"
    ESCAPED = "escaped"
    # intervals that are explicitly NOT custody
    ON_BAIL = "on_bail"
    ABSCONDING = "absconding"
    # informational
    BAIL_GRANTED = "bail_granted"


COUNTING_INTERVALS = {CustodyType.POLICE_CUSTODY, CustodyType.JUDICIAL_CUSTODY, CustodyType.HOSPITALISED_IN_CUSTODY}
STARTERS = {CustodyType.ARREST, CustodyType.RE_ARREST, CustodyType.SURRENDERED, CustodyType.TRANSFER}
TERMINATORS = {CustodyType.RELEASED, CustodyType.ESCAPED}
EXCLUSION_INTERVALS = {CustodyType.ON_BAIL, CustodyType.ABSCONDING}


class Attribution(StrEnum):
    ACCUSED = "accused"
    PROSECUTION = "prosecution"
    COURT = "court"
    BOTH = "both"
    OTHER = "other"
    UNKNOWN = "unknown"


class ConvictionStatus(StrEnum):
    FINAL = "final"
    UNDER_APPEAL = "under_appeal"
    SET_ASIDE = "set_aside"
    JUVENILE = "juvenile"


class Modifier(StrEnum):
    ATTEMPT = "attempt"
    ABETMENT = "abetment"                       # act abetted was committed
    ABETMENT_NOT_COMMITTED = "abetment_not_committed"
    CONSPIRACY = "conspiracy"
    COMMON_INTENTION = "common_intention"


@dataclass(frozen=True)
class SourceRef:
    """Where a fact came from: document + page + character span."""
    document_id: str
    page: int = 1
    start: int = 0
    end: int = 0
    text: str = ""
    doc_type: str = ""

    def label(self) -> str:
        return f"{self.doc_type or 'document'} {self.document_id} p.{self.page}"


@dataclass
class Charge:
    act: str
    section: str
    modifier: Modifier | None = None
    offence_date: date | None = None
    added_on: date | None = None
    dropped_on: date | None = None
    confidence: float = 1.0
    source: SourceRef | None = None
    aggravated: bool = False  # e.g. highway robbery at night / repeat theft
    id: str = ""

    @property
    def label(self) -> str:
        mod = f" ({self.modifier.value})" if self.modifier else ""
        return f"{self.act} {self.section}{mod}"


@dataclass
class CustodyEvent:
    type: CustodyType
    start: date
    end: date | None = None
    case_id: str | None = None  # None = not tied to a case (e.g. generic jail record)
    jail: str | None = None
    confidence: float = 1.0
    is_primary_source: bool = True
    source: SourceRef | None = None
    id: str = ""


@dataclass
class Hearing:
    date: date
    next_date: date | None = None
    reason_text: str = ""
    attribution: Attribution = Attribution.UNKNOWN
    attribution_confidence: float = 0.0
    reviewer_verified: bool = False
    source: SourceRef | None = None
    id: str = ""


@dataclass
class Conviction:
    case_id: str
    date: date
    status: ConvictionStatus
    offence: str = ""
    source: SourceRef | None = None
    id: str = ""


@dataclass
class Case:
    id: str
    status: CaseStatus
    charges: list[Charge] = field(default_factory=list)
    hearings: list[Hearing] = field(default_factory=list)
    cnr: str = ""
    offence_date: date | None = None
    fir_date: date | None = None
    first_remand_date: date | None = None
    charge_sheet_date: date | None = None
    default_bail_application_date: date | None = None
    bail_granted_date: date | None = None
    conviction_date: date | None = None
    acquittal_date: date | None = None
    status_confidence: float = 1.0

    def active_charges(self, on: date) -> list[Charge]:
        return [c for c in self.charges if c.dropped_on is None or c.dropped_on > on]


@dataclass
class Person:
    id: str
    name: str
    cases: list[Case] = field(default_factory=list)
    custody_events: list[CustodyEvent] = field(default_factory=list)
    convictions: list[Conviction] = field(default_factory=list)
    dob: date | None = None
    gender: str | None = None


@dataclass
class ComputeContext:
    today: date
    confidence_threshold: float = 0.8
    computed_at: datetime | None = None
