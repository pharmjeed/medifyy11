"""مصادقة ثنائية TOTP — RFC 6238 (خطوة 30ث، 6 أرقام، SHA-1) بلا اعتماديات خارجية.

تُستخدم لحسابات السوبر أدمن (DOC-20 §١.٣): السرّ يُخزَّن مشفّراً عمودياً،
ورموز الاسترداد تُخزَّن هاش SHA-256 وتُصرف لمرة واحدة.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time

TOTP_STEP_SECONDS = 30
TOTP_DIGITS = 6
RECOVERY_CODES_COUNT = 8


def generate_secret() -> str:
    """سرّ Base32 (160 بت) — الصيغة التي تقبلها تطبيقات المصادقة."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def otpauth_uri(secret: str, username: str, issuer: str = "Medify-SA") -> str:
    """رابط otpauth للإدخال في تطبيق المصادقة (يدوياً أو كـ QR يولّده المتصفح)."""
    return f"otpauth://totp/{issuer}:{username}?secret={secret}&issuer={issuer}&digits={TOTP_DIGITS}&period={TOTP_STEP_SECONDS}"


def _hotp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32.upper() + "=" * (-len(secret_b32) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** TOTP_DIGITS)
    return str(code).zfill(TOTP_DIGITS)


def verify_totp(secret_b32: str, code: str, window: int = 1, at: float | None = None) -> bool:
    """تحقق بنافذة ±window خطوة (سماحية انحراف ساعة الجوال)."""
    if not code or not code.strip().isdigit():
        return False
    code = code.strip()
    counter = int((at if at is not None else time.time()) // TOTP_STEP_SECONDS)
    return any(
        hmac.compare_digest(_hotp(secret_b32, counter + delta), code)
        for delta in range(-window, window + 1)
    )


def generate_recovery_codes() -> list[str]:
    """رموز استرداد لمرة واحدة — تُعرض مرة واحدة وتُخزَّن هاشاتها فقط."""
    return [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(RECOVERY_CODES_COUNT)]


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(code.strip().lower().encode()).hexdigest()
