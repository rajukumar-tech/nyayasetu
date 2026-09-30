"""Account lifecycle rules shared by the admin and DLSA endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.models import Alert, Person, User


def deactivate(db: Session, actor: User, u: User, reason: str = "") -> list[str]:
    """Deactivate an account. For a lawyer, every assigned prisoner becomes UNASSIGNED (never silently kept or
    handed to someone else) and a high-severity alert asks the DLSA to reassign. Returns the unassigned IDs.
    Old sessions stop working at once because every request re-checks `active`."""
    before = {"active": u.active}
    u.active = False
    moved: list[str] = []
    if u.role == "legal_aid_lawyer":
        for p in db.scalars(select(Person).where(Person.assigned_lawyer_id == u.id)):
            p.assigned_lawyer_id = None
            moved.append(p.id)
            audit(db, actor, "unassign_lawyer", "person", p.id, before=u.id, after=None,
                  detail="lawyer account deactivated", commit=False)
            key = f"{p.id}:REASSIGN:{u.id}:{datetime.now(timezone.utc).isoformat()}"
            db.add(Alert(person_id=p.id, kind="LAWYER_REASSIGNMENT_NEEDED", severity="high", dedupe_key=key,
                         message=f"{p.canonical_name}: the assigned lawyer's account was deactivated — assign a new lawyer.",
                         channel_log=[{"channel": "in_app", "at": datetime.now(timezone.utc).isoformat(), "status": "stored"}]))
    audit(db, actor, "deactivate_user", "user", u.id, before=before, after={"active": False, "unassigned": len(moved)},
          detail=reason or None, commit=False)
    db.commit()
    return moved


def activate(db: Session, actor: User, u: User) -> str:
    """Approve (first activation) or reactivate. Reactivation does NOT restore earlier assignments."""
    action = "approve_user" if u.approved_at is None else "reactivate_user"
    u.active = True
    if u.approved_at is None:
        u.approved_at = datetime.now(timezone.utc)
    audit(db, actor, action, "user", u.id, before={"active": False}, after={"active": True})
    return action
