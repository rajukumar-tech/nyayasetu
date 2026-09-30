"""SQLAlchemy models. Every extracted fact keeps value + source span + method + confidence + review status."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Table, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(timezone.utc)


case_persons = Table(
    "case_persons", Base.metadata,
    Column("case_id", ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True),
    Column("person_id", ForeignKey("persons.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(40))
    hashed_password: Mapped[str] = mapped_column(String(200))
    jail: Mapped[str | None] = mapped_column(String(200))       # jail_staff scope
    district: Mapped[str | None] = mapped_column(String(200))   # dlsa_admin scope
    language: Mapped[str] = mapped_column(String(8), default="en")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # None = awaiting approval
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    created_by: Mapped[str | None] = mapped_column(String(32))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # older sessions are refused


class RevokedToken(Base):
    """Signed-out session tokens (by JWT id) — a token is refused after logout even before it expires."""
    __tablename__ = "revoked_tokens"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(32))
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Person(Base):
    __tablename__ = "persons"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    canonical_name: Mapped[str] = mapped_column(String(300))
    name_variants: Mapped[list[str]] = mapped_column(JSON, default=list)
    relative_name_variants: Mapped[list[str]] = mapped_column(JSON, default=list)  # father/husband
    relation: Mapped[str | None] = mapped_column(String(8))  # s/o, d/o, w/o
    gender: Mapped[str | None] = mapped_column(String(16))
    dob: Mapped[date | None] = mapped_column(Date)
    dob_uncertainty_years: Mapped[float | None] = mapped_column(Float)
    age_at_offence: Mapped[int | None] = mapped_column(Integer)
    addresses: Mapped[list[str]] = mapped_column(JSON, default=list)
    identifiers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_juvenile_at_offence: Mapped[bool] = mapped_column(Boolean, default=False)
    is_foreign_national: Mapped[bool] = mapped_column(Boolean, default=False)
    vulnerability: Mapped[list[str]] = mapped_column(JSON, default=list)  # woman, elderly, disabled, serious_illness
    jail: Mapped[str | None] = mapped_column(String(200))
    district: Mapped[str | None] = mapped_column(String(200))
    state: Mapped[str | None] = mapped_column(String(100))
    assigned_lawyer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    merged_into_id: Mapped[str | None] = mapped_column(ForeignKey("persons.id"))
    synthetic_truth_id: Mapped[str | None] = mapped_column(String(64))  # ground truth for evaluation only
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    cases: Mapped[list["Case"]] = relationship(secondary=case_persons, back_populates="persons")
    custody_events: Mapped[list["CustodyEvent"]] = relationship(back_populates="person", cascade="all, delete-orphan")
    convictions: Mapped[list["Conviction"]] = relationship(back_populates="person", cascade="all, delete-orphan")


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    cnr: Mapped[str | None] = mapped_column(String(32), index=True)
    case_numbers: Mapped[list[str]] = mapped_column(JSON, default=list)
    court: Mapped[str | None] = mapped_column(String(300))
    district: Mapped[str | None] = mapped_column(String(200))
    state: Mapped[str | None] = mapped_column(String(100))
    fir_number: Mapped[str | None] = mapped_column(String(50))
    police_station: Mapped[str | None] = mapped_column(String(200))
    fir_year: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="investigation")
    status_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    offence_date: Mapped[date | None] = mapped_column(Date)
    fir_date: Mapped[date | None] = mapped_column(Date)
    first_remand_date: Mapped[date | None] = mapped_column(Date)
    charge_sheet_date: Mapped[date | None] = mapped_column(Date)
    default_bail_application_date: Mapped[date | None] = mapped_column(Date)
    bail_granted_date: Mapped[date | None] = mapped_column(Date)
    conviction_date: Mapped[date | None] = mapped_column(Date)
    acquittal_date: Mapped[date | None] = mapped_column(Date)
    facts_summary: Mapped[str | None] = mapped_column(Text)  # from documents; used for judgment retrieval

    persons: Mapped[list[Person]] = relationship(secondary=case_persons, back_populates="cases")
    charges: Mapped[list["Charge"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    hearings: Mapped[list["Hearing"]] = relationship(back_populates="case", cascade="all, delete-orphan",
                                                     order_by="Hearing.date")


class Charge(Base):
    __tablename__ = "charges"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    act: Mapped[str] = mapped_column(String(20))
    section: Mapped[str] = mapped_column(String(40))
    modifier: Mapped[str | None] = mapped_column(String(40))
    offence_date: Mapped[date | None] = mapped_column(Date)
    added_on: Mapped[date | None] = mapped_column(Date)
    dropped_on: Mapped[date | None] = mapped_column(Date)
    aggravated: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[dict | None] = mapped_column(JSON)
    case: Mapped[Case] = relationship(back_populates="charges")


class CustodyEvent(Base):
    __tablename__ = "custody_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    person_id: Mapped[str] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"))
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"))
    type: Mapped[str] = mapped_column(String(40))
    start: Mapped[date] = mapped_column(Date)
    end: Mapped[date | None] = mapped_column(Date)
    jail: Mapped[str | None] = mapped_column(String(200))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    is_primary_source: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[dict | None] = mapped_column(JSON)
    person: Mapped[Person] = relationship(back_populates="custody_events")


class Hearing(Base):
    __tablename__ = "hearings"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    next_date: Mapped[date | None] = mapped_column(Date)
    outcome_text: Mapped[str] = mapped_column(Text, default="")
    reason_text: Mapped[str] = mapped_column(Text, default="")
    delay_attribution: Mapped[str] = mapped_column(String(20), default="unknown")
    attribution_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    attribution_method: Mapped[str | None] = mapped_column(String(40))
    reviewer_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[dict | None] = mapped_column(JSON)
    case: Mapped[Case] = relationship(back_populates="hearings")


class Conviction(Base):
    __tablename__ = "convictions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    person_id: Mapped[str] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"))
    case_id: Mapped[str] = mapped_column(String(32))  # may reference a case outside the system
    date: Mapped[date] = mapped_column(Date)
    offence: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20))
    source: Mapped[dict | None] = mapped_column(JSON)
    person: Mapped[Person] = relationship(back_populates="convictions")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    person_id: Mapped[str | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    doc_type: Mapped[str] = mapped_column(String(40), default="unknown")
    doc_type_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    language: Mapped[str | None] = mapped_column(String(20))
    scripts: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="uploaded")  # uploaded|ocr_done|extracted|failed|needs_review
    pages: Mapped[list[dict]] = mapped_column(JSON, default=list)  # [{page, text, confidence, boxes:[...]}]
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    storage_path: Mapped[str | None] = mapped_column(String(500))
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @property
    def text(self) -> str:
        return "\n".join(p.get("text", "") for p in self.pages)


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    method: Mapped[str] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    raw_output: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ExtractedFact(Base):
    __tablename__ = "extracted_facts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    person_id: Mapped[str | None] = mapped_column(ForeignKey("persons.id", ondelete="SET NULL"))
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"))
    field: Mapped[str] = mapped_column(String(60))
    value: Mapped[Any] = mapped_column(JSON)
    page: Mapped[int] = mapped_column(Integer, default=1)
    span_start: Mapped[int] = mapped_column(Integer, default=0)
    span_end: Mapped[int] = mapped_column(Integer, default=0)
    span_text: Mapped[str] = mapped_column(Text, default="")
    method: Mapped[str] = mapped_column(String(40))  # regex | llm | regex+llm | manual
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    review_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|confirmed|corrected|rejected
    corrected_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)

    @property
    def effective_value(self) -> Any:
        return self.corrected_value if self.review_status == "corrected" else self.value


class ReviewItem(Base):
    __tablename__ = "review_items"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    kind: Mapped[str] = mapped_column(String(40))  # extraction | identity_match | delay_attribution | document_mismatch
    ref_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved
    resolution: Mapped[dict | None] = mapped_column(JSON)
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("kind", "ref_id", name="uq_review_kind_ref"),)


class MergeEvent(Base):
    __tablename__ = "merge_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    kept_person_id: Mapped[str] = mapped_column(ForeignKey("persons.id"))
    merged_person_id: Mapped[str] = mapped_column(ForeignKey("persons.id"))
    snapshot: Mapped[dict] = mapped_column(JSON)  # what moved, for un-merge
    score: Mapped[float | None] = mapped_column(Float)
    performed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    undone: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EligibilityResult(Base):
    __tablename__ = "eligibility_results"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    person_id: Mapped[str] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    rule_version: Mapped[str] = mapped_column(String(40))
    legal_data_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), index=True)
    eligible_from_date: Mapped[date | None] = mapped_column(Date)
    days_overdue: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    input_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class DefenseInsight(Base):
    __tablename__ = "defense_insights"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    person_id: Mapped[str] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(60))
    category: Mapped[str] = mapped_column(String(4))  # A-F
    severity: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    explanation: Mapped[str] = mapped_column(Text)
    next_steps: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list[dict]] = mapped_column(JSON, default=list)
    legal_basis: Mapped[list[str]] = mapped_column(JSON, default=list)
    judgments: Mapped[list[dict]] = mapped_column(JSON, default=list)
    rank_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="new")  # new | accepted | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("person_id", "case_id", "code", name="uq_insight"),)


class Draft(Base):
    __tablename__ = "drafts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    person_id: Mapped[str] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(40))
    language: Mapped[str] = mapped_column(String(8), default="en")
    content: Mapped[str] = mapped_column(Text)
    grounding: Mapped[list[dict]] = mapped_column(JSON, default=list)
    verifier_report: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | approved | rejected
    versions: Mapped[list[dict]] = mapped_column(JSON, default=list)  # tracked lawyer edits
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    person_id: Mapped[str] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str | None] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_resolved: Mapped[bool] = mapped_column(Boolean, default=False)  # closed because the condition no longer holds
    channel_log: Mapped[list[dict]] = mapped_column(JSON, default=list)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    user_id: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[str | None] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[Any] = mapped_column(JSON, nullable=True)
    after: Mapped[Any] = mapped_column(JSON, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text)


class LegalVerification(Base):
    __tablename__ = "legal_verifications"
    record_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    verified: Mapped[bool] = mapped_column(Boolean)
    verified_by: Mapped[str] = mapped_column(String(200))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    note: Mapped[str | None] = mapped_column(Text)
