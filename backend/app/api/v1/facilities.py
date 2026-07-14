"""المنشأة والاشتراك والفوترة — DOC-05 §٣ (FR-100)."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...audit import audit
from ...db import get_db, get_system_db, set_rls_context
from ...deps import AdminAuth, pagination
from ...envelope import ok, paginated
from ...errors import MedifyError
from ...models import (
    CodingSystemConfig,
    Facility,
    IntegrationConfig,
    Invoice,
    SeatEvent,
    Subscription,
    User,
)
from ...notify import notify_admins
from ...security import hash_password
from ...services.billing import (
    create_payment_session,
    get_subscription,
    issue_invoice,
    seats_used,
    verify_webhook_signature,
)

router = APIRouter()
SystemDB = Annotated[Session, Depends(get_system_db)]
DB = Annotated[Session, Depends(get_db)]


class RegisterAdminIn(BaseModel):
    full_name: str = Field(min_length=1)
    username: str = Field(min_length=3)
    email: EmailStr  # إلزامي للأدمن — قناة الاستعادة (DOC-04)
    password: str = Field(min_length=8)


class RegisterFacilityIn(BaseModel):
    name: str = Field(min_length=2)
    commercial_reg: str = Field(min_length=4)
    admin: RegisterAdminIn
    seats: int = Field(ge=1, le=500)


@router.post("/facilities/register", status_code=201)
def register_facility(body: RegisterFacilityIn, db: SystemDB):
    """W-002 (معالج 3 خطوات) — النقطة العامة الوحيدة (FR-101)."""
    exists = db.execute(
        select(Facility).where(Facility.commercial_reg == body.commercial_reg)
    ).scalar_one_or_none()
    if exists is not None:
        raise MedifyError("MDF-4041", details={"reason": "commercial_reg_taken"})

    facility = Facility(name=body.name, commercial_reg=body.commercial_reg, status="active")
    db.add(facility)
    db.flush()
    admin = User(
        facility_id=facility.id,
        role="admin",
        full_name=body.admin.full_name,
        username=body.admin.username,
        email=body.admin.email,
        password_hash=hash_password(body.admin.password),
        is_active=True,
    )
    db.add(admin)
    subscription = Subscription(facility_id=facility.id, seats_total=body.seats, plan="monthly")
    db.add(subscription)
    db.flush()
    db.add(SeatEvent(subscription_id=subscription.id, delta=body.seats, reason="expand", actor_user_id=admin.id))
    # أنظمة الترميز الافتراضية — الحزمة السعودية (FR-301)
    for system in ("ICD10AM", "ACHI", "SBS", "SFDA"):
        db.add(CodingSystemConfig(facility_id=facility.id, system=system, version="2024", is_active=True))
    db.add(IntegrationConfig(facility_id=facility.id, mode="test"))
    issue_invoice(db, subscription, body.seats)
    audit(db, facility.id, "facility.registered", "facility", facility.id, admin.id, {"seats": body.seats})
    return ok({"facility_id": str(facility.id), "admin_username": admin.username})


@router.get("/subscription")
def subscription_status(ctx: AdminAuth, db: DB):
    subscription = get_subscription(db, ctx.facility_id)
    used = seats_used(db, ctx.facility_id)
    events = db.execute(
        select(SeatEvent).where(SeatEvent.subscription_id == subscription.id).order_by(SeatEvent.created_at.desc()).limit(50)
    ).scalars().all()
    return ok({
        "plan": subscription.plan,
        "seats_total": subscription.seats_total,
        "seats_used": used,
        "seats_available": subscription.seats_total - used,
        "seat_events": [
            {
                "id": str(event.id),
                "delta": event.delta,
                "reason": event.reason,
                "at": event.created_at.isoformat(),
            }
            for event in events
        ],
    })


class SeatsPatchIn(BaseModel):
    seats_total: int = Field(ge=1, le=500)


@router.patch("/subscription/seats")
def patch_seats(body: SeatsPatchIn, ctx: AdminAuth, db: DB):
    """توسعة/تقليص (FR-102) — التقليص لا ينزل عن المقاعد المستهلكة (DOC-09 §٢)."""
    subscription = get_subscription(db, ctx.facility_id)
    used = seats_used(db, ctx.facility_id)
    if body.seats_total < used:
        raise MedifyError("MDF-4221", details={"seats_used": used, "requested": body.seats_total})
    delta = body.seats_total - subscription.seats_total
    if delta != 0:
        subscription.seats_total = body.seats_total
        db.add(SeatEvent(
            subscription_id=subscription.id,
            delta=delta,
            reason="expand" if delta > 0 else "reduce",
            actor_user_id=ctx.user_id,
        ))
        if delta > 0:
            issue_invoice(db, subscription, delta)  # تناسبي — توضيحي حتى قفل الأسعار
        audit(db, ctx.facility_id, "subscription.seats_changed", "subscription", subscription.id, ctx.user_id, {"delta": delta})
    return ok({"seats_total": subscription.seats_total, "seats_used": used})


@router.get("/invoices")
def list_invoices(ctx: AdminAuth, db: DB, page: int = 1, per_page: int = 25):
    page, per_page = pagination(page, per_page)
    base = select(Invoice).where(Invoice.facility_id == ctx.facility_id)
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = db.execute(base.order_by(Invoice.issued_at.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return paginated([_invoice_out(invoice) for invoice in rows], total, page, per_page)


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: uuid.UUID, ctx: AdminAuth, db: DB):
    invoice = db.execute(select(Invoice).where(Invoice.id == invoice_id)).scalar_one_or_none()
    if invoice is None:
        raise MedifyError("MDF-4041")
    return ok(_invoice_out(invoice))


def _invoice_out(invoice: Invoice) -> dict:
    return {
        "id": str(invoice.id),
        "number": invoice.number,
        "period_start": invoice.period_start.isoformat(),
        "period_end": invoice.period_end.isoformat(),
        "amount_sar": str(invoice.amount_sar),
        "vat_sar": str(invoice.vat_sar),
        "total_sar": str(invoice.amount_sar + invoice.vat_sar),
        "status": invoice.status,
        "issued_at": invoice.issued_at.isoformat(),
        "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
    }


@router.post("/invoices/{invoice_id}/pay")
def pay_invoice(invoice_id: uuid.UUID, ctx: AdminAuth, db: DB):
    """W-208/FR-104 — جلسة دفع لدى المزود المحلي؛ الفشل → MDF-4228."""
    invoice = db.execute(select(Invoice).where(Invoice.id == invoice_id)).scalar_one_or_none()
    if invoice is None:
        raise MedifyError("MDF-4041")
    if invoice.status == "paid":
        raise MedifyError("MDF-4228", details={"reason": "already_paid"})
    if invoice.status == "void":
        raise MedifyError("MDF-4228", details={"reason": "void_invoice"})
    try:
        session = create_payment_session(invoice)
    except Exception as exc:
        raise MedifyError("MDF-4228") from exc
    invoice.provider_ref = session["provider_ref"]
    audit(db, ctx.facility_id, "invoice.payment_started", "invoice", invoice.id, ctx.user_id)
    return ok({"checkout_url": session["checkout_url"], "provider_ref": session["provider_ref"]})


class PaymentWebhookIn(BaseModel):
    provider_ref: str
    status: str  # paid | failed


@router.post("/webhooks/payments")
def payments_webhook(body: PaymentWebhookIn, request: Request, db: SystemDB):
    """نقطة عامة بتوقيع مُتحقق — تحدّث الفاتورة وترفع تعليق المنشأة (D-08)."""
    signature = request.headers.get("X-Medify-Signature", "")
    if not verify_webhook_signature(body.model_dump(), signature):
        raise MedifyError("MDF-4031", details={"reason": "bad_signature"})
    invoice = db.execute(
        select(Invoice).where(Invoice.provider_ref == body.provider_ref)
    ).scalar_one_or_none()
    if invoice is None:
        raise MedifyError("MDF-4041")

    if body.status == "paid":
        invoice.status = "paid"
        invoice.paid_at = dt.datetime.now(dt.timezone.utc)
        facility = db.execute(select(Facility).where(Facility.id == invoice.facility_id)).scalar_one()
        remaining_overdue = db.execute(
            select(func.count(Invoice.id)).where(
                Invoice.facility_id == facility.id,
                Invoice.status.in_(["overdue"]),
                Invoice.id != invoice.id,
            )
        ).scalar_one()
        if facility.status == "suspended" and remaining_overdue == 0:
            facility.status = "active"
            audit(db, facility.id, "facility.suspension_lifted", "facility", facility.id, None,
                  {"invoice": invoice.number})
        audit(db, facility.id, "invoice.paid", "invoice", invoice.id, None, {"number": invoice.number})
    else:
        invoice.status = "overdue"
        set_rls_context(db, invoice.facility_id)  # للإشعارات فقط
        notify_admins(db, invoice.facility_id, "ad.payment_failed", {"invoice": invoice.number})
        audit(db, invoice.facility_id, "invoice.payment_failed", "invoice", invoice.id, None)
    return ok({"processed": True})
