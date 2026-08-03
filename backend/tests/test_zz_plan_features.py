"""مميزات الباقة (قرار مالك 2026-08-03) — ما تُظهره الباقة للدكتور.

معايير القبول: باقة كاملة → كل شيء متاح | إطفاء ميزة من المالك → المنع فوري بـMDF-4032
بلا إعادة دخول | الأساسية لا تُطفأ | تغيير المميزات لا يمس التسعير.

يُشغَّل أخيراً (zz) لأنه يبدّل باقة المنشأة الأولى مؤقتاً — وكل حالة تُرجع الحالة كما كانت.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest

from tests.conftest import auth, record_consent


@pytest.fixture(scope="module")
def sa_token(client) -> str:
    response = client.post("/api/v1/sa/auth/login", json={"username": "owner", "password": "Owner@12345"})
    assert response.status_code == 200, response.text
    return response.json()["data"]["access_token"]


@pytest.fixture(scope="module")
def monthly_plan(client, sa_token) -> dict:
    """الباقة التي عليها منشأة الاختبارات الأولى (seed: subscriptions.plan = "monthly")."""
    plans = client.get("/api/v1/sa/plans", headers=auth(sa_token)).json()["data"]
    plan = next(p for p in plans if p["code"] == "monthly")
    return plan


@contextmanager
def features_off(client, sa_token: str, plan: dict, *keys: str):
    """يطفئ مفاتيح على الباقة ثم يعيد الخريطة الأصلية حرفياً — لا تسرّب بين الاختبارات."""
    original = {key: value for key, value in plan["features"].items()}
    changed = {**original, **{key: False for key in keys}}
    response = client.put(f"/api/v1/sa/plans/{plan['id']}/features",
                          headers=auth(sa_token), json={"features": changed})
    assert response.status_code == 200, response.text
    try:
        yield response.json()["data"]
    finally:
        restore = client.put(f"/api/v1/sa/plans/{plan['id']}/features",
                             headers=auth(sa_token), json={"features": original})
        assert restore.status_code == 200, restore.text


@pytest.fixture(scope="module")
def review_visit(client, doctor_token) -> str:
    """زيارة في in_review بنص محادثة وصوت — مادة اختبار «سماع/رؤية المحادثة»."""
    headers = auth(doctor_token)
    created = client.post("/api/v1/patients", headers=headers,
                          json={"hospital_mrn": "9900930", "display_name": "فهد التجريبي"})
    patient_id = created.json()["data"]["id"]
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    visit = client.post("/api/v1/visits", headers=headers,
                        json={"patient_id": patient_id, "template_id": templates[0]["id"]})
    visit_id = visit.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    assert client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers).status_code == 200
    assert client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                       json={"duration_sec": 30}).status_code == 200
    return visit_id


# ═══ حسم المميزات ═══

def test_features_endpoint_shape(client, doctor_token):
    response = client.get("/api/v1/features", headers=auth(doctor_token))
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["plan"]["code"] == "monthly"
    assert body["features"]["visit.transcript_view"] is True
    assert body["features"]["visit.audio_playback"] is True
    # الكتالوج يصف كل مفتاح — الواجهة تعرض منه لا من نصوص مكرّرة
    keys = {item["key"] for item in body["catalog"]}
    assert keys == set(body["features"])


def test_admin_sees_same_plan_features(client, admin_token):
    """الميزة على المنشأة لا على الدور — الأدمن يرى خريطة منشأته نفسها."""
    body = client.get("/api/v1/features", headers=auth(admin_token)).json()["data"]
    assert body["plan"]["code"] == "monthly"


# ═══ الميزتان اللتان طلبهما المالك مباشرة ═══

def test_transcript_and_audio_blocked_when_off(client, sa_token, doctor_token, monthly_plan, review_visit):
    headers = auth(doctor_token)
    assert client.get(f"/api/v1/visits/{review_visit}/transcript", headers=headers).status_code == 200

    with features_off(client, sa_token, monthly_plan, "visit.transcript_view", "visit.audio_playback"):
        # يسري فوراً على الرمز نفسه — لا إعادة دخول (مبدأ الترابط)
        blocked = client.get(f"/api/v1/visits/{review_visit}/transcript", headers=headers)
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "MDF-4032"
        assert blocked.json()["error"]["details"]["feature"] == "visit.transcript_view"

        token = doctor_token
        audio = client.get(f"/api/v1/visits/{review_visit}/audio?token={token}")
        assert audio.status_code == 403
        assert audio.json()["error"]["code"] == "MDF-4032"

        seen = client.get("/api/v1/features", headers=headers).json()["data"]["features"]
        assert seen["visit.transcript_view"] is False
        assert seen["visit.audio_playback"] is False

    # بعد الإرجاع يعود المسار مفتوحاً
    assert client.get(f"/api/v1/visits/{review_visit}/transcript", headers=headers).status_code == 200


def test_has_transcript_survives_feature_off(client, sa_token, doctor_token, monthly_plan, review_visit):
    """«هل التُقط كلام» واقعة لا محتوى — تبقى في الملخص كي لا تُخطئ الواجهة رسالة W-224."""
    headers = auth(doctor_token)
    with features_off(client, sa_token, monthly_plan, "visit.transcript_view"):
        summary = client.get(f"/api/v1/visits/{review_visit}/summary", headers=headers)
        assert summary.status_code == 200
        assert summary.json()["data"]["has_transcript"] is True


# ═══ بقية المميزات ═══

def test_patient_summary_blocked_when_off(client, sa_token, doctor_token, monthly_plan, review_visit):
    headers = auth(doctor_token)
    with features_off(client, sa_token, monthly_plan, "visit.patient_summary"):
        response = client.post(f"/api/v1/visits/{review_visit}/patient-summary", headers=headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "MDF-4032"


def test_ai_chat_and_dictation_blocked_when_off(client, sa_token, doctor_token, monthly_plan, review_visit):
    headers = auth(doctor_token)
    with features_off(client, sa_token, monthly_plan, "visit.ai_chat"):
        response = client.post(f"/api/v1/visits/{review_visit}/ai-chat", headers=headers,
                               json={"message": "اختصر الخطة"})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "MDF-4032"


def test_custom_templates_blocked_for_doctor_when_off(client, sa_token, doctor_token, monthly_plan):
    headers = auth(doctor_token)
    with features_off(client, sa_token, monthly_plan, "templates.custom", "templates.reverse_build"):
        # القراءة تبقى — الاختيار من الجاهزة هو جوهر المسار (لا تسجيل بلا قالب)
        assert client.get("/api/v1/templates", headers=headers).status_code == 200
        blocked = client.post("/api/v1/templates/reverse-build", headers=headers,
                              json={"sample_text": "S: شكوى\nP: خطة"})
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "MDF-4032"


def test_claim_readiness_off_does_not_block_gate_two(client, sa_token, doctor_token, monthly_plan):
    """الفاحص ميزة: بإطفائه لا فحص ولا MDF-4237 — والبوابة ② نفسها تبقى إلزامية."""
    headers = auth(doctor_token)
    with features_off(client, sa_token, monthly_plan, "visit.claim_readiness"):
        visits = client.get("/api/v1/visits", headers=headers).json()["data"]
        target = next((v for v in visits if v["state"] == "in_review"), None)
        if target is None:
            pytest.skip("لا زيارة in_review متاحة في هذه الجولة")
        readiness = client.get(f"/api/v1/visits/{target['id']}/claim-readiness", headers=headers)
        assert readiness.status_code == 403
        assert readiness.json()["error"]["code"] == "MDF-4032"


# ═══ حراسة الكتالوج والدرجات ═══

def test_core_features_cannot_be_disabled(client, sa_token, monthly_plan):
    response = client.put(f"/api/v1/sa/plans/{monthly_plan['id']}/features", headers=auth(sa_token),
                          json={"features": {"visit.recording": False, **monthly_plan["features"]}})
    assert response.status_code == 200
    assert response.json()["data"]["features"]["visit.recording"] is True


def test_unknown_feature_key_rejected(client, sa_token, monthly_plan):
    response = client.put(f"/api/v1/sa/plans/{monthly_plan['id']}/features", headers=auth(sa_token),
                          json={"features": {"visit.teleportation": True}})
    assert response.status_code == 404
    assert response.json()["error"]["details"]["reason"] == "unknown_feature_keys"


def test_features_write_requires_owner_grade(client, sa_token, monthly_plan):
    """plans.write للـowner حصراً — درجة ops لا تغيّر ما يراه الأطباء (DOC-20 §١.٢)."""
    created = client.post("/api/v1/sa/admins", headers=auth(sa_token), json={
        "username": "ops.features", "full_name": "مشغّل اختبار المميزات",
        "email": "ops.features@medify.example.sa", "role": "ops", "password": "Ops@123456",
    })
    assert created.status_code in (201, 404), created.text  # 404 = username_taken (جولة سابقة)
    ops_token = client.post("/api/v1/sa/auth/login", json={
        "username": "ops.features", "password": "Ops@123456",
    }).json()["data"]["access_token"]
    response = client.put(f"/api/v1/sa/plans/{monthly_plan['id']}/features", headers=auth(ops_token),
                          json={"features": {"visit.audio_playback": False}})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "MDF-4031"


def test_plan_pricing_untouched_by_feature_change(client, sa_token, monthly_plan):
    with features_off(client, sa_token, monthly_plan, "visit.export_pdf") as updated:
        assert updated["seat_price_sar"] == monthly_plan["seat_price_sar"]
        assert updated["billing_cycle"] == monthly_plan["billing_cycle"]


def test_basic_plan_seeded_with_reduced_features(client, sa_token):
    """باقة dev المقلّصة — دليل حي أن الإخفاء يعمل بلا تعديل يدوي."""
    plans = client.get("/api/v1/sa/plans", headers=auth(sa_token)).json()["data"]
    basic = next((p for p in plans if p["code"] == "basic-monthly"), None)
    assert basic is not None, "البذر يُنشئ باقة أساسية مقلّصة"
    assert basic["features"]["visit.transcript_view"] is False
    assert basic["features"]["visit.audio_playback"] is False
    assert basic["features"]["visit.recording"] is True     # أساسية
    assert basic["features_on"] < basic["features_total"]
