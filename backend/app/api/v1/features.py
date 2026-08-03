"""مميزات باقة المنشأة — ما تعرضه الواجهة (قرار مالك 2026-08-03).

نقطة قراءة واحدة لكل مستخدم مسجّل: الواجهة تسألها مرة عند الدخول لتخفي ما ليس في الباقة.
الإخفاء تجربة استخدام؛ المنع الفعلي في `services/features.require_feature` على كل نقطة.
"""
from __future__ import annotations

from fastapi import APIRouter

from ...deps import Auth, DB
from ...envelope import ok
from ...features import catalog_out
from ...services.features import facility_plan, plan_features

router = APIRouter()


@router.get("/features")
def my_features(ctx: Auth, db: DB):
    """خريطة `{مفتاح: مفعّل}` لباقة المنشأة + الكتالوج للعرض (لا محتوى سريرياً)."""
    plan = facility_plan(db, ctx.facility_id)
    return ok({
        "plan": None if plan is None else {
            "code": plan.code,
            "name_ar": plan.name_ar,
            "name_en": plan.name_en,
        },
        "features": plan_features(plan),
        "catalog": catalog_out(),
    })
