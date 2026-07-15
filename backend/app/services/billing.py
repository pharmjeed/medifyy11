"""الفوترة والمقاعد — DOC-09: مقعد لكل دكتور، VAT 15% مفصولة، PAYMENT_ENGINE=mock (D-10)."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import MedifyError
from ..models import Invoice, Plan, Subscription, User

SEAT_PRICE_SAR = Decimal("400.00")  # احتياطي إن غابت الباقة — يُقفل وفق DOC-09 §٤ بعد التحقق الميداني
VAT_RATE = Decimal("0.15")


def plan_seat_price(db: Session, plan_code: str) -> Decimal:
    """سعر المقعد من كتالوج الباقات (هجرة 0002) — الاحتياطي الثابت إن غاب الرمز."""
    price = db.execute(
        select(Plan.seat_price_sar).where(Plan.code == plan_code)
    ).scalar_one_or_none()
    return price if price is not None else SEAT_PRICE_SAR


def seats_used(db: Session, facility_id: uuid.UUID) -> int:
    return db.execute(
        select(func.count(User.id)).where(
            User.facility_id == facility_id,
            User.role == "doctor",
            User.is_active == True,  # noqa: E712
        )
    ).scalar_one()


def get_subscription(db: Session, facility_id: uuid.UUID) -> Subscription:
    subscription = db.execute(
        select(Subscription).where(Subscription.facility_id == facility_id)
    ).scalar_one_or_none()
    if subscription is None:
        raise MedifyError("MDF-4041")
    return subscription


def ensure_seat_available(db: Session, facility_id: uuid.UUID) -> None:
    subscription = get_subscription(db, facility_id)
    if seats_used(db, facility_id) >= subscription.seats_total:
        raise MedifyError("MDF-4221", details={"seats_total": subscription.seats_total})


def issue_invoice(db: Session, subscription: Subscription, seats: int, note: str = "") -> Invoice:
    amount = plan_seat_price(db, subscription.plan) * seats
    vat = (amount * VAT_RATE).quantize(Decimal("0.01"))
    now = dt.datetime.now(dt.timezone.utc)
    invoice = Invoice(
        facility_id=subscription.facility_id,
        subscription_id=subscription.id,
        number=f"INV-{now.year}-{uuid.uuid4().hex[:6].upper()}",
        period_start=now,
        period_end=now + dt.timedelta(days=30),
        amount_sar=amount,
        vat_sar=vat,
        status="due",
        issued_at=now,
    )
    db.add(invoice)
    db.flush()
    return invoice


def create_payment_session(invoice: Invoice) -> dict[str, str]:
    """PAYMENT_ENGINE=mock: جلسة دفع وهمية — المزود الحقيقي (Moyasar/Tap) يُقفل لاحقاً (DOC-09 §٣)."""
    provider_ref = f"pay_{uuid.uuid4().hex[:12]}"
    return {
        "provider": "mock",
        "provider_ref": provider_ref,
        "checkout_url": f"/pay/mock/{provider_ref}",
    }


def sign_webhook_payload(payload: dict) -> str:
    secret = get_settings().payment_webhook_secret.encode()
    body = json.dumps(payload, sort_keys=True).encode()
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def verify_webhook_signature(payload: dict, signature: str) -> bool:
    return hmac.compare_digest(sign_webhook_payload(payload), signature)
