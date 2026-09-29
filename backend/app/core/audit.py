from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def audit(db: Session, user: User | None, action: str, entity_type: str, entity_id: str | None = None,
          before: Any = None, after: Any = None, detail: str | None = None, commit: bool = True) -> None:
    """Append-only audit entry. Called for every view, edit and decision."""
    db.add(AuditLog(user_id=user.id if user else None, role=user.role if user else "system", action=action,
                    entity_type=entity_type, entity_id=entity_id, before=before, after=after, detail=detail))
    if commit:
        db.commit()
