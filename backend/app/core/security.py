from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db
from app.models import RevokedToken, User

_bearer = HTTPBearer(auto_error=False)


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.jwt_expiry_minutes)
    return jwt.encode({"sub": user.id, "role": user.role, "exp": exp, "iat": now, "jti": uuid.uuid4().hex},
                      settings.jwt_secret, algorithm="HS256")


def token_claims(creds: HTTPAuthorizationCredentials | None) -> dict:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    try:
        return jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or invalid — please sign in again")


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)) -> User:
    payload = token_claims(creds)
    if payload.get("jti") and db.get(RevokedToken, payload["jti"]) is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "You have signed out — please sign in again")
    user = db.get(User, payload.get("sub"))
    # checked on EVERY request: a deactivated account's old tokens stop working immediately
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found or disabled")
    changed = user.password_changed_at
    if changed is not None and payload.get("iat") is not None:
        changed = changed if changed.tzinfo else changed.replace(tzinfo=timezone.utc)
        if datetime.fromtimestamp(payload["iat"], timezone.utc) < changed.replace(microsecond=0):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your password was changed — please sign in again")
    return user
