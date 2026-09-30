"""Nightly monitoring: recompute eligibility for every active prisoner and raise alerts.

Idempotent: every alert has a deterministic `dedupe_key` (unique in the DB), so re-running
the job — or running it twice in one night — never creates duplicates. Unacknowledged
alerts older than `alert_escalation_days` are escalated once."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Alert, Person
from app.services.eligibility import ComputeOutcome, compute_for_person, load_kb

log = logging.getLogger("nyayasetu.alerts")

CRITICAL_CODES = {"CRITICAL_MUST_RELEASE": "Detained beyond the maximum sentence",
                  "CRITICAL_ACQUITTED_DETAINED": "Acquitted/discharged but still detained",
                  "CRITICAL_BAIL_NOT_FURNISHED": "Bail granted but not released (surety not furnished)",
                  "URGENT_DEFAULT_BAIL": "Default-bail right has accrued — apply before the charge sheet is filed",
                  "DEFAULT_BAIL_WINDOW_SOON": "Default-bail window opens within days"}


class Channel:
    name = "in_app"

    def send(self, alert: Alert, person: Person) -> dict:
        return {"channel": self.name, "at": datetime.now(timezone.utc).isoformat(), "status": "stored"}


class StubChannel(Channel):
    """Email / SMS / WhatsApp are pluggable; these stubs only log what would be sent."""

    def __init__(self, name: str):
        self.name = name

    def send(self, alert: Alert, person: Person) -> dict:
        log.info("[%s stub] %s — %s", self.name, person.canonical_name, alert.message)
        return {"channel": self.name, "at": datetime.now(timezone.utc).isoformat(), "status": "stub_not_sent"}


CHANNELS: list[Channel] = [Channel(), StubChannel("email"), StubChannel("sms"), StubChannel("whatsapp")]


@dataclass
class RunReport:
    persons: int = 0
    recomputed: int = 0
    changed: int = 0
    alerts_created: int = 0
    escalated: int = 0


def _raise(db: Session, person: Person, case_id: str | None, kind: str, severity: str, message: str, key: str,
           valid: set[str] | None = None) -> bool:
    if valid is not None:
        valid.add(key)
    existing = db.scalar(select(Alert).where(Alert.dedupe_key == key))
    if existing is not None:
        if existing.acknowledged_at is None and existing.message != message:
            existing.message = message  # keep open alerts current (e.g. the number of days overdue)
        if existing.auto_resolved:  # the condition came back: reopen instead of silently staying closed
            existing.auto_resolved, existing.acknowledged_at, existing.acknowledged_by = False, None, None
            existing.message = message
            existing.channel_log = existing.channel_log + [{"channel": "system", "at": datetime.now(timezone.utc).isoformat(),
                                                            "status": "reopened: condition holds again"}]
        return False
    a = Alert(person_id=person.id, case_id=case_id, kind=kind, severity=severity, message=message, dedupe_key=key)
    a.channel_log = [ch.send(a, person) for ch in CHANNELS]
    db.add(a)
    db.flush()
    return True


# alert kinds that describe a CURRENT condition; they are closed automatically when it stops holding
CONDITION_KINDS = set(CRITICAL_CODES) | {"ELIGIBLE_OVERDUE", "ELIGIBLE_IN_30", "ELIGIBLE_IN_7", "ELIGIBLE_IN_0"}


def alerts_for(db: Session, person: Person, out: ComputeOutcome, today: date, reason: str = "nightly") -> int:
    n = 0
    valid: set[str] = set()  # dedupe keys of alerts whose condition holds right now
    for c in out.row.result["cases"]:
        cid = c["case_id"]
        status = c["status"]
        codes = [status] + [f["code"] for f in c.get("findings", [])]
        for code in codes:
            if code in CRITICAL_CODES:
                sev = "critical" if code != "DEFAULT_BAIL_WINDOW_SOON" else "high"
                n += _raise(db, person, cid, code, sev, f"{person.canonical_name}: {CRITICAL_CODES[code]}.",
                            f"{person.id}:{cid}:{code}", valid)
        if status == "ELIGIBLE":
            n += _raise(db, person, cid, "ELIGIBLE_OVERDUE", "high",
                        f"{person.canonical_name}: eligible under Section 479 since {c['eligible_from_date']} "
                        f"({c['days_overdue']} days overdue).", f"{person.id}:{cid}:ELIGIBLE", valid)
        if status == "NOT_YET" and c.get("projected_date"):
            days = (date.fromisoformat(c["projected_date"]) - today).days
            for window in (30, 7, 0):
                if days <= window:
                    n += _raise(db, person, cid, f"ELIGIBLE_IN_{window}", "medium" if window else "high",
                                f"{person.canonical_name}: becomes eligible on {c['projected_date']} ({days} days).",
                                f"{person.id}:{cid}:ELIGIBLE_IN_{window}:{c['projected_date']}", valid)
                    break
    if out.changed and out.previous_status and out.previous_status != out.row.status and reason != "nightly":
        what = {"document": "a new document", "release": "a recorded release", "transfer": "a recorded transfer",
                "review": "a reviewer decision", "recompute": "a recompute", "case_update": "a case update",
                "custody": "a custody update"}.get(reason, reason)
        n += _raise(db, person, None, "RESULT_CHANGED", "high",
                    f"{person.canonical_name}: {what} changed the result from {out.previous_status} to "
                    f"{out.row.status}.", f"{person.id}:CHANGED:{out.row.input_hash[:16]}")
    # close alerts whose condition no longer holds (released, charge sheet filed, status changed, ...)
    now = datetime.now(timezone.utc)
    for a in db.scalars(select(Alert).where(Alert.person_id == person.id, Alert.acknowledged_at.is_(None),
                                            Alert.kind.in_(CONDITION_KINDS))):
        if a.dedupe_key not in valid:
            a.auto_resolved, a.acknowledged_at = True, now
            a.channel_log = a.channel_log + [{"channel": "system", "at": now.isoformat(),
                                              "status": f"auto-resolved: condition no longer holds ({reason})"}]
    return n


def run_nightly(db: Session, today: date | None = None) -> RunReport:
    today = today or settings.today()
    kb = load_kb(db)
    rep = RunReport()
    persons = db.scalars(select(Person).where(Person.merged_into_id.is_(None))).all()
    for p in persons:
        rep.persons += 1
        out = compute_for_person(db, p, kb, commit=False)
        rep.recomputed += 1
        rep.changed += int(out.changed)
        rep.alerts_created += alerts_for(db, p, out, today)
    rep.escalated = escalate(db)
    db.commit()
    return rep


def escalate(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=settings.alert_escalation_days)
    n = 0
    for a in db.scalars(select(Alert).where(Alert.acknowledged_at.is_(None), Alert.escalated.is_(False))):
        created = a.created_at if a.created_at.tzinfo else a.created_at.replace(tzinfo=timezone.utc)
        if created <= cutoff and a.severity in ("critical", "high"):
            a.escalated = True
            a.channel_log = a.channel_log + [{"channel": "escalation", "at": now.isoformat(),
                                              "status": "escalated to DLSA dashboard"}]
            n += 1
    return n
