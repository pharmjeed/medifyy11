"""تشفير عمودي تطبيقي (D-05) لأعمدة PII والنصوص السريرية — مفتاح من البيئة حصراً."""
from __future__ import annotations

import base64
import hashlib
import json
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from .config import get_settings

_PREFIX = "enc:v1:"


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().column_encryption_key
    try:
        return Fernet(key.encode())
    except Exception:
        # اشتقاق مفتاح Fernet صالح من أي سر بيئة (urlsafe b64 لـ32 بايت)
        digest = hashlib.sha256(key.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_str(value: str) -> str:
    return _PREFIX + _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_str(value: str) -> str:
    if not value.startswith(_PREFIX):
        return value  # بيانات قديمة/غير مشفرة (seed انتقالي)
    try:
        return _fernet().decrypt(value[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:  # مفتاح خاطئ — لا نكشف المحتوى
        raise RuntimeError("COLUMN_ENCRYPTION_KEY mismatch") from exc


class EncryptedText(TypeDecorator):
    """عمود نصي مشفّر تطبيقياً — يُخزَّن كنص ولا يُفهرس بمحتواه."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        return None if value is None else encrypt_str(value)

    def process_result_value(self, value: str | None, dialect: Any) -> str | None:
        return None if value is None else decrypt_str(value)


class EncryptedJSON(TypeDecorator):
    """jsonb مشفّر — يُخزَّن نصاً مشفّراً (المحتوى سريري: لا استعلام داخله)."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        return None if value is None else encrypt_str(json.dumps(value, ensure_ascii=False))

    def process_result_value(self, value: str | None, dialect: Any) -> Any:
        return None if value is None else json.loads(decrypt_str(value))
