"""Role-based access control. One table of permissions; scoping rules for prisoner records."""
from __future__ import annotations

from enum import StrEnum

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import current_user
from app.db import get_db
from app.models import Person, User


class Role(StrEnum):
    LAWYER = "legal_aid_lawyer"
    JAIL_STAFF = "jail_staff"
    DLSA_ADMIN = "dlsa_admin"
    REVIEWER = "reviewer"
    SYSTEM_ADMIN = "system_admin"


class Perm(StrEnum):
    VIEW_PRISONER = "view_prisoner"
    VIEW_DEFENSE_INSIGHTS = "view_defense_insights"
    DECIDE_DEFENSE_INSIGHTS = "decide_defense_insights"
    EDIT_DRAFTS = "edit_drafts"
    CREATE_DRAFTS = "create_drafts"
    CORRECT_FACTS = "correct_facts"
    UPLOAD_DOCUMENTS = "upload_documents"
    REVIEW_QUEUE = "review_queue"
    DISTRICT_DASHBOARD = "district_dashboard"
    ASSIGN_LAWYERS = "assign_lawyers"
    MANAGE_LEGAL_DATA = "manage_legal_data"
    MANAGE_USERS = "manage_users"
    VIEW_AUDIT = "view_audit"
    MERGE_PERSONS = "merge_persons"
    ACK_ALERTS = "ack_alerts"
    SUPERINTENDENT_APPLICATION = "superintendent_application"
    CREATE_PRISONER = "create_prisoner"
    CUSTODY_EVENTS = "custody_events"      # record transfers and releases
    UPDATE_CASE = "update_case"            # record case outcomes (acquittal, conviction, charge sheet, ...)
    MANAGE_LAWYERS = "manage_lawyers"      # create/approve/activate/deactivate legal-aid lawyer accounts
    VIEW_REGISTER = "view_register"        # the prisoner register (names, jail, status, lawyer) — no case details


P = Perm
PERMISSIONS: dict[Role, set[Perm]] = {
    Role.LAWYER: {P.VIEW_PRISONER, P.VIEW_DEFENSE_INSIGHTS, P.DECIDE_DEFENSE_INSIGHTS, P.EDIT_DRAFTS, P.CREATE_DRAFTS,
                  P.CORRECT_FACTS, P.UPLOAD_DOCUMENTS, P.ACK_ALERTS},
    # jail staff record custody events (transfer, release, case outcomes) — documents are uploaded only by the
    # assigned lawyer, so every document in a case file comes through the person responsible for that case
    Role.JAIL_STAFF: {P.VIEW_PRISONER, P.ACK_ALERTS, P.SUPERINTENDENT_APPLICATION, P.CREATE_PRISONER,
                      P.CUSTODY_EVENTS, P.UPDATE_CASE},
    Role.DLSA_ADMIN: {P.VIEW_PRISONER, P.DISTRICT_DASHBOARD, P.ASSIGN_LAWYERS, P.ACK_ALERTS, P.MANAGE_LAWYERS,
                      P.VIEW_REGISTER},
    Role.REVIEWER: {P.REVIEW_QUEUE, P.CORRECT_FACTS, P.MERGE_PERSONS},
    # The system admin does TECHNICAL work only: user accounts and password resets, the audit log, legal-data
    # verification and nightly monitoring. Prisoners are added by jail staff, lawyers are added and assigned by the
    # DLSA, new records are checked by the reviewer — the admin does none of that, and never sees case details,
    # documents, Defense Insights or drafts.
    Role.SYSTEM_ADMIN: {P.MANAGE_USERS, P.VIEW_AUDIT, P.MANAGE_LEGAL_DATA},
}


def has_perm(user: User, perm: Perm) -> bool:
    return perm in PERMISSIONS.get(Role(user.role), set())


def require(perm: Perm):
    def dep(user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
        if not has_perm(user, perm):
            from app.core.audit import audit
            audit(db, user, "access_denied", "permission", perm.value, detail=f"role {user.role} lacks {perm.value}")
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your role ({user.role}) cannot {perm.value.replace('_', ' ')}")
        return user
    return dep


def can_see_person(user: User, person: Person) -> bool:
    """Record-level scope: lawyers see assigned prisoners, jail staff their jail, DLSA their district."""
    role = Role(user.role)
    if role == Role.LAWYER:
        return person.assigned_lawyer_id == user.id
    if role == Role.JAIL_STAFF:
        return bool(user.jail) and person.jail == user.jail
    if role == Role.DLSA_ADMIN:
        return bool(user.district) and person.district == user.district
    return False  # reviewers work through the review queue; the admin through the register


def can_see_insights(user: User, person: Person) -> bool:
    """Defense Insights are privileged strategy: the assigned lawyer only."""
    return Role(user.role) == Role.LAWYER and person.assigned_lawyer_id == user.id


NOT_FOUND = "Record not found or not available to your account"


def not_found() -> HTTPException:
    """One response for "does not exist" and "exists but outside your scope", so an out-of-scope
    user cannot probe which prisoner / document / draft IDs exist."""
    return HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)


def ensure_person_access(user: User, person: Person | None, db: Session | None = None,
                         resource: str = "person", resource_id: str | None = None) -> Person:
    if person is None or person.merged_into_id:
        raise not_found()
    if not can_see_person(user, person):
        if db is not None:
            from app.core.audit import audit
            audit(db, user, "access_denied", resource, resource_id or person.id, detail="outside assignment/scope")
        raise not_found()
    return person
