"""JWT قصير + refresh (DOC-05 §١) · argon2id · قفل 5 محاولات (DOC-16, D-07)."""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import threading
import uuid
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .config import get_settings
from .errors import MedifyError

_hasher = PasswordHasher()  # argon2id افتراضياً


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def create_access_token(user_id: uuid.UUID, facility_id: uuid.UUID, role: str) -> str:
    s = get_settings()
    payload = {
        "sub": str(user_id),
        "facility_id": str(facility_id),
        "role": role,
        "type": "access",
        "exp": _now() + dt.timedelta(minutes=s.access_token_minutes),
        "iat": _now(),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def create_sa_access_token(admin_id: uuid.UUID) -> str:
    """رمز وصول السوبر أدمن — scope=platform بلا facility_id (لا يمر أبداً من deps.authenticated)."""
    s = get_settings()
    payload = {
        "sub": str(admin_id),
        "role": "super_admin",
        "scope": "platform",
        "type": "access",
        "exp": _now() + dt.timedelta(minutes=s.access_token_minutes),
        "iat": _now(),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def create_sa_refresh_token(admin_id: uuid.UUID) -> str:
    s = get_settings()
    payload = {
        "sub": str(admin_id),
        "role": "super_admin",
        "scope": "platform",
        "type": "refresh",
        "jti": secrets.token_urlsafe(16),
        "exp": _now() + dt.timedelta(days=s.refresh_token_days),
        "iat": _now(),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def create_refresh_token(user_id: uuid.UUID, facility_id: uuid.UUID, role: str) -> str:
    s = get_settings()
    payload = {
        "sub": str(user_id),
        "facility_id": str(facility_id),
        "role": role,
        "type": "refresh",
        "jti": secrets.token_urlsafe(16),
        "exp": _now() + dt.timedelta(days=s.refresh_token_days),
        "iat": _now(),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    s = get_settings()
    try:
        payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise MedifyError("MDF-4012") from exc
    except jwt.InvalidTokenError as exc:
        raise MedifyError("MDF-4012") from exc
    if payload.get("type") != expected_type:
        raise MedifyError("MDF-4012")
    return payload


def hash_token(token: str) -> str:
    """هاش رموز الاستعادة — لا يُخزَّن الرمز الخام أبداً (DOC-04)."""
    return hashlib.sha256(token.encode()).hexdigest()


class LoginLockout:
    """قفل الحساب بعد 5 محاولات فاشلة خلال 15 دقيقة (DOC-16 §٢، D-07) — ذاكرة/Redis."""

    MAX_ATTEMPTS = 5
    WINDOW_SECONDS = 15 * 60

    def __init__(self) -> None:
        self._attempts: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _key(self, facility_key: str, username: str) -> str:
        return f"{facility_key}:{username}"

    def is_locked(self, facility_key: str, username: str) -> bool:
        import time

        with self._lock:
            attempts = self._attempts.get(self._key(facility_key, username), [])
            cutoff = time.time() - self.WINDOW_SECONDS
            attempts = [a for a in attempts if a > cutoff]
            self._attempts[self._key(facility_key, username)] = attempts
            return len(attempts) >= self.MAX_ATTEMPTS

    def record_failure(self, facility_key: str, username: str) -> None:
        import time

        with self._lock:
            self._attempts.setdefault(self._key(facility_key, username), []).append(time.time())

    def reset(self, facility_key: str, username: str) -> None:
        with self._lock:
            self._attempts.pop(self._key(facility_key, username), None)


lockout = LoginLockout()
