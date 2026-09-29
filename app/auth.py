"""Email+password auth with signed session cookies (JWT via python-jose)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import (
    COOKIE_SAMESITE,
    COOKIE_SECURE,
    SESSION_COOKIE,
    SESSION_DAYS,
    SESSION_SECRET,
)
from app.database import get_db
from app.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    # bcrypt truncates at 72 bytes
    return pwd_context.hash(password[:72])


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password[:72], password_hash)
    except Exception:
        return False


def create_session_token(user_id: int, email: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    payload = {"sub": str(user_id), "email": email, "exp": exp}
    return jwt.encode(payload, SESSION_SECRET, algorithm=ALGORITHM)


def decode_session_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SESSION_SECRET, algorithms=[ALGORITHM])
    except JWTError:
        return None


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=SESSION_DAYS * 86400,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE, path="/")


def get_user_from_request(request: Request, db: Session) -> Optional[User]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    payload = decode_session_token(token)
    if not payload:
        return None
    try:
        uid = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        return None
    return db.get(User, uid)


def get_optional_user(
    request: Request, db: Session = Depends(get_db)
) -> Optional[User]:
    return get_user_from_request(request, db)


def require_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    user = get_user_from_request(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in required.")
    return user


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()
