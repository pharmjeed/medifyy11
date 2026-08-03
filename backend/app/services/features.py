"""حسم مميزات المنشأة من باقتها وإنفاذها — قرار مالك 2026-08-03.

السلسلة: `users.facility_id` → `subscriptions.plan` → `plans.code` → `plans.features`.
الحسم لحظي بلا كاش عمداً: مبدأ الترابط (DOC-20 تعديل ١) يقضي بأن فعل المالك يسري فوراً على
الدكتور — استعلام واحد مفهرس أرخص من شرح تأخّر دقيقة للعميل.

`plans` جدول منصّي بلا RLS ودور التطبيق يقرأه (هجرة 0002)، و`subscriptions` عليه RLS —
فالدالة تعمل داخل جلسة الدكتور/الأدمن نفسها بلا تجاوز عزل.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import MedifyError
from ..features import CORE_KEYS, FEATURE_BY_KEY, FEATURE_CATALOG
from ..models import Plan, Subscription


def default_features() -> dict[str, bool]:
    """الخريطة حين لا باقة (منشأة بلا اشتراك، أو باقة محذوفة) — الافتراضات كما في الكتالوج."""
    return {f.key: True if f.core else f.default for f in FEATURE_CATALOG}


def plan_features(plan: Plan | None) -> dict[str, bool]:
    """الخريطة الفعّالة لباقة: الافتراض ثم اختيار الباقة، والأساسية مفعّلة دوماً.

    مفتاح مخزّن لم يعد في الكتالوج يُهمل (ميزة أُزيلت من الكود)، ومفتاح جديد لم تحسمه الباقة
    يأخذ افتراضه — فترقية الكود لا تُسقط ميزة عن منشأة قائمة ولا تفتح شيئاً بلا قصد.
    """
    if plan is None:
        return default_features()
    stored = plan.features if isinstance(plan.features, dict) else {}
    return {
        f.key: True if f.core else bool(stored.get(f.key, f.default))
        for f in FEATURE_CATALOG
    }


def facility_plan(db: Session, facility_id: uuid.UUID) -> Plan | None:
    subscription = db.execute(
        select(Subscription).where(Subscription.facility_id == facility_id)
    ).scalar_one_or_none()
    if subscription is None:
        return None
    return db.execute(select(Plan).where(Plan.code == subscription.plan)).scalar_one_or_none()


def facility_features(db: Session, facility_id: uuid.UUID) -> dict[str, bool]:
    return plan_features(facility_plan(db, facility_id))


def feature_enabled(db: Session, facility_id: uuid.UUID, key: str) -> bool:
    if key not in FEATURE_BY_KEY:
        raise ValueError(f"مفتاح ميزة غير معرّف في الكتالوج: {key}")
    if key in CORE_KEYS:
        return True
    return facility_features(db, facility_id)[key]


def require_feature(db: Session, facility_id: uuid.UUID, key: str) -> None:
    """الحارس الخادمي — الواجهة تُخفي، وهذا يمنع (MDF-4032)."""
    if not feature_enabled(db, facility_id, key):
        definition = FEATURE_BY_KEY[key]
        raise MedifyError("MDF-4032", details={
            "feature": key,
            "feature_name_ar": definition.name_ar,
            "feature_name_en": definition.name_en,
        })
