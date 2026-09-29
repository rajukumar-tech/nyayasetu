"""Role-based access control. One table of permissions; scoping rules for prisoner records."""
from __future__ import annotations

from enum import StrEnum

from fastapi import Depends, HTTPException, status

from app.core.security import current_user
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


P = Perm
PERMISSIONS: dict[Role, set[Perm]] = {
    Role.LAWYER: {P.VIEW_PRISONER, P.VIEW_DEFENSE_INSIGHTS, P.DECIDE_DEFENSE_INSIGHTS, P.EDIT_DRAFTS, P.CREATE_DRAFTS,
                  P.CORRECT_FACTS, P.UPLOAD_DOCUMENTS, P.ACK_ALERTS},
    Role.JAIL_STAFF: {P.VIEW_PRISONER, P.UPLOAD_DOCUMENTS, P.ACK_ALERTS, P.SUPERINTENDENT_APPLICATION},
    Role.DLSA_ADMIN: {P.VIEW_PRISONER, P.DISTRICT_DASHBOARD, P.ASSIGN_LAWYERS, P.ACK_ALERTS},
    Role.REVIEWER: {P.REVIEW_QUEUE, P.CORRECT_FACTS, P.MERGE_PERSONS},
    Role.SYSTEM_ADMIN: set(Perm),  # admins see insights too — every view is audited
}


def has_perm(user: User, perm: Perm) -> bool:
    return perm in PERMISSIONS.get(Role(user.role), set())


def require(perm: Perm):
    def dep(user: User = Depends(current_user)) -> User:
        if not has_perm(user, perm):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your role ({user.role}) cannot {perm.value.replace('_', ' ')}")
        return user
    return dep


def can_see_person(user: User, person: Person) -> bool:
    """Record-level scope: lawyers see assigned prisoners, jail staff their jail, DLSA their district."""
    role = Role(user.role)
    if role == Role.SYSTEM_ADMIN:
        return True
    if role == Role.LAWYER:
        return person.assigned_lawyer_id == user.id
    if role == Role.JAIL_STAFF:
        return bool(user.jail) and person.jail == user.jail
    if role == Role.DLSA_ADMIN:
        return bool(user.district) and person.district == user.district
    return False  # reviewers work only through the review queue


def can_see_insights(user: User, person: Person) -> bool:
    """Defense Insights are privileged strategy: assigned lawyer only (+ admin, audited)."""
    role = Role(user.role)
    if role == Role.SYSTEM_ADMIN:
        return True
    return role == Role.LAWYER and person.assigned_lawyer_id == user.id


def ensure_person_access(user: User, person: Person | None) -> Person:
    if person is None or person.merged_into_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prisoner record not found")
    if not can_see_person(user, person):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This prisoner is outside your assignment")
    return person
