from __future__ import annotations

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
    status: Literal["draft", "approved", "rejected"] | None = None


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
