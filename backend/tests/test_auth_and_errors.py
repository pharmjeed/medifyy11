"""المصادقة + غلاف الأخطاء + رموز MDF — DOC-05 §٢ / DOC-13."""
from __future__ import annotations

import os
from pathlib import Path

from app.errors import MDF_CATALOG
from tests.conftest import auth


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"


def test_mdf_catalog_is_exactly_27():
    """22 (DOC-13 v1.2) + MDF-4015/4229 (DOC-20) + MDF-4230/4231/4232 (بوابتا الاعتماد
    وموافقة المريض — توجيه المالك 2026-07-22)."""
    assert len(MDF_CATALOG) == 27
    assert "MDF-4015" in MDF_CATALOG and "MDF-4229" in MDF_CATALOG
    # رموز توجيه المالك: موافقة المريض + بوابتا الاعتماد
    assert {"MDF-4230", "MDF-4231", "MDF-4232"} <= set(MDF_CATALOG)
    for code, (status, ar, en) in MDF_CATALOG.items():
        assert code.startswith("MDF-")
        assert ar and en  # ثنائية اللغة إلزامية


def test_login_success_returns_envelope(client, admin_token):
    response = client.post("/api/v1/auth/login", json={
        "facility": "1010456789", "username": "admin", "password": "Admin@12345",
    })
    body = response.json()
    assert "data" in body and "meta" in body
    assert body["data"]["user"]["role"] == "admin"
    assert body["data"]["user"]["facility_name"] == "مجمع الشفاء الطبي"


def test_login_wrong_password_mdf4011(client):
    response = client.post("/api/v1/auth/login", json={
        "facility": "1010456789", "username": "admin", "password": "wrong-pass",
    })
    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "MDF-4011"
    assert error["message_ar"] and error["message_en"]


def test_login_disabled_doctor_mdf4013(client):
    response = client.post("/api/v1/auth/login", json={
        "facility": "1010456789", "username": "dr.reem", "password": "Doctor@12345",
    })
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "MDF-4013"


def test_lockout_after_5_failures(client):
    for _ in range(5):
        client.post("/api/v1/auth/login", json={
            "facility": "1010456789", "username": "dr.fahad", "password": "bad",
        })
    response = client.post("/api/v1/auth/login", json={
        "facility": "1010456789", "username": "dr.fahad", "password": "Doctor@12345",
    })
    assert response.status_code == 401  # مقفول رغم صحة كلمة المرور (DOC-16 §٢)
    from app.security import lockout
    lockout.reset("1010456789", "dr.fahad")


def test_me_requires_token(client):
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "MDF-4012"


def test_me_returns_profile(client, doctor_token):
    response = client.get("/api/v1/me", headers=auth(doctor_token))
    data = response.json()["data"]
    assert data["role"] == "doctor"
    assert data["clinic_name"] == "عيادة الباطنة"
    assert data["specialty"] == "باطنة"


def test_refresh_flow(client):
    login = client.post("/api/v1/auth/login", json={
        "facility": "1010456789", "username": "dr.ahmad", "password": "Doctor@12345",
    })
    assert "medify_refresh" in login.cookies
    refresh = client.post("/api/v1/auth/refresh", cookies={"medify_refresh": login.cookies["medify_refresh"]})
    assert refresh.status_code == 200
    assert refresh.json()["data"]["access_token"]


def test_forgot_and_reset_password_w206(client):
    outbox = Path(os.environ["OUTBOX_DIR"])
    before = set(outbox.glob("*.json")) if outbox.exists() else set()
    response = client.post("/api/v1/auth/forgot-password", json={
        "commercial_reg": "1010456789", "username": "admin",
    })
    assert response.status_code == 200  # استجابة عامة موحدة
    new_files = set(outbox.glob("*.json")) - before
    assert new_files, "رابط الاستعادة يُرسل لبريد الأدمن (mock outbox)"
    import json
    payload = json.loads(new_files.pop().read_text(encoding="utf-8"))
    token = payload["payload"]["reset_url"].split("reset_token=")[1]

    reset = client.post("/api/v1/auth/reset-password", json={
        "token": token, "new_password": "Admin@12345",  # نعيدها كما كانت
    })
    assert reset.status_code == 200

    # الرمز يُستخدم مرة واحدة → MDF-4014
    again = client.post("/api/v1/auth/reset-password", json={
        "token": token, "new_password": "Another@123",
    })
    assert again.status_code == 401
    assert again.json()["error"]["code"] == "MDF-4014"


def test_reset_password_invalid_token_mdf4014(client):
    response = client.post("/api/v1/auth/reset-password", json={
        "token": "not-a-real-token", "new_password": "Whatever@123",
    })
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "MDF-4014"


def test_forgot_password_does_not_reveal_accounts(client):
    response = client.post("/api/v1/auth/forgot-password", json={
        "commercial_reg": "0000000000", "username": "ghost",
    })
    assert response.status_code == 200  # نفس الاستجابة تماماً


def test_role_guard_mdf4031(client, doctor_token):
    response = client.get("/api/v1/subscription", headers=auth(doctor_token))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "MDF-4031"


def test_rate_limit_mdf4291():
    from app.errors import MedifyError
    from app.ratelimit import SlidingWindowLimiter
    limiter = SlidingWindowLimiter()
    limiter.check("x", limit=2)
    limiter.check("x", limit=2)
    try:
        limiter.check("x", limit=2)
        raise AssertionError("يجب أن يرفع MDF-4291")
    except MedifyError as exc:
        assert exc.code == "MDF-4291"
        assert "Retry-After" in exc.headers
