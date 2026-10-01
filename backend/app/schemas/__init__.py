from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


class FactPatch(BaseModel):
    action: Literal["confirm", "correct", "reject"]
    value: Any | None = None
    note: str | None = None


class InsightPatch(BaseModel):
    status: Literal["accepted", "rejected", "new"]
    note: str | None = None


class DraftCreate(BaseModel):
    case_id: str
    type: Literal["section_479", "default_bail", "regular_bail", "plea_bargaining", "discharge", "speedy_trial",
                  "surety_modification"]
    language: Literal["en", "kn"] = "en"
    use_llm: bool = True


class DraftPatch(BaseModel):
    content: str | None = None
    status: Literal["draft", "rejected"] | None = None  # drafts are never "approved" in the app: the lawyer signs and files


class ReviewResolve(BaseModel):
    action: Literal["confirm", "correct", "reject", "link", "not_same", "set_attribution"]
    value: Any | None = None
    note: str | None = None


class MergeIn(BaseModel):
    keep_id: str
    other_id: str
    score: float | None = None


class VerifyIn(BaseModel):
    verified: bool
    note: str = Field(min_length=5, description="What was checked, e.g. 'India Code PDF, s.379 punishment clause'")


class UserCreate(BaseModel):
    email: str
    name: str
    role: Literal["legal_aid_lawyer", "jail_staff", "dlsa_admin", "reviewer", "system_admin"]
    password: str = Field(min_length=10)
    jail: str | None = None
    district: str | None = None


class AssignIn(BaseModel):
    lawyer_id: str


class UserPatch(BaseModel):
    role: Literal["legal_aid_lawyer", "jail_staff", "dlsa_admin", "reviewer", "system_admin"] | None = None
    active: bool | None = None
    jail: str | None = None
    district: str | None = None


class ChargeIn(BaseModel):
    act: str = Field(min_length=2, max_length=20)
    section: str = Field(min_length=1, max_length=40)


class CaseIn(BaseModel):
    court: str = Field(min_length=2, max_length=300)
    case_number: str | None = Field(None, max_length=200)
    cnr: str | None = Field(None, max_length=32)
    fir_number: str | None = Field(None, max_length=50)
    police_station: str | None = Field(None, max_length=200)
    offence_date: date | None = None
    charges: list[ChargeIn] = Field(min_length=1)
    arrest_date: date
    first_remand_date: date | None = None
    charge_sheet_date: date | None = None
    custody_status: Literal["in_custody", "on_bail", "released"] = "in_custody"
    status_change_date: date | None = None  # bail/release date when custody_status is not in_custody


class PersonCreate(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    relative_name: str | None = Field(None, max_length=300)
    relation: Literal["s/o", "d/o", "w/o"] | None = None
    gender: Literal["male", "female", "other"] | None = None
    dob: date | None = None
    address: str | None = Field(None, max_length=500)
    jail: str | None = Field(None, max_length=200)
    district: str | None = Field(None, max_length=200)
    case: CaseIn


class TransferIn(BaseModel):
    to_jail: str = Field(min_length=3, max_length=200)
    to_district: str | None = Field(None, max_length=200)
    on: date = Field(alias="date")  # (a field literally named `date` would shadow the type)
    note: str | None = Field(None, max_length=500)


class ReleaseIn(BaseModel):
    on: date = Field(alias="date")
    case_id: str | None = None
    note: str | None = Field(None, max_length=500)


class CasePatch(BaseModel):
    status: Literal["investigation", "charge_sheet_filed", "trial", "convicted", "acquitted", "discharged", "disposed"] | None = None
    first_remand_date: date | None = None
    charge_sheet_date: date | None = None
    default_bail_application_date: date | None = None
    bail_granted_date: date | None = None
    acquittal_date: date | None = None
    conviction_date: date | None = None


class LawyerCreate(BaseModel):
    email: str = Field(min_length=5, max_length=200)
    name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=10, max_length=200)
    approve: bool = False


class PasswordReset(BaseModel):
    password: str = Field(min_length=10, max_length=200)
