"""اختبارات طبقة السوبر أدمن /sa — المصادقة والعزل والباقات والفوترة اليدوية."""
from __future__ import annotations

import pytest

from .conftest import auth


@pytest.fixture(scope="module")
def sa_token(client) -> str:
    response = client.post("/api/v1/sa/auth/login", json={"username": "owner", "password": "Owner@12345"})
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["admin"]["role"] == "owner"  # الدرجة (DOC-20 §١.٢) — النطاق scope=platform في الرمز
    return body["access_token"]


# ═══ المصادقة والعزل ═══

def test_sa_login_wrong_password(client):
    response = client.post("/api/v1/sa/auth/login", json={"username": "owner", "password": "wrong-pass"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "MDF-4011"


def test_sa_me(client, sa_token):
    response = client.get("/api/v1/sa/me", headers=auth(sa_token))
    assert response.status_code == 200
    assert response.json()["data"]["username"] == "owner"


def test_facility_admin_token_rejected_on_sa(client, admin_token):
    """رمز أدمن المنشأة لا يفتح المنصة."""
    response = client.get("/api/v1/sa/overview", headers=auth(admin_token))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "MDF-4031"


def test_sa_token_rejected_on_facility_routes(client, sa_token):
    """رمز السوبر أدمن لا يفتح مسارات المنشآت (scope=platform)."""
    response = client.get("/api/v1/subscription", headers=auth(sa_token))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "MDF-4031"


def test_sa_routes_require_token(client):
    response = client.get("/api/v1/sa/facilities")
    assert response.status_code == 401


# ═══ النظرة والمنشآت ═══

def test_overview_counts(client, sa_token):
    response = client.get("/api/v1/sa/overview", headers=auth(sa_token))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["facilities"]["total"] >= 2  # منشأتا البذر
    assert data["users"]["doctors_total"] >= 5
    assert "outstanding_sar" in data["invoices"]


def test_list_and_detail_facility(client, sa_token):
    listing = client.get("/api/v1/sa/facilities?q=الشفاء", headers=auth(sa_token))
    assert listing.status_code == 200
    rows = listing.json()["data"]
    assert len(rows) == 1
    fid = rows[0]["id"]
    assert rows[0]["plan"] == "monthly"

    detail = client.get(f"/api/v1/sa/facilities/{fid}", headers=auth(sa_token))
    assert detail.status_code == 200
    data = detail.json()["data"]
    assert data["facility"]["commercial_reg"] == "1010456789"
    assert data["subscription"]["seats_used"] >= 1
    assert data["subscription"]["plan_info"]["code"] == "monthly"
    roles = {user["role"] for user in data["users"]}
    assert roles == {"admin", "doctor"}


def test_suspend_and_reactivate_facility(client, sa_token):
    fid = client.get("/api/v1/sa/facilities?q=النخبة", headers=auth(sa_token)).json()["data"][0]["id"]
    suspended = client.patch(f"/api/v1/sa/facilities/{fid}", headers=auth(sa_token), json={"status": "suspended"})
    assert suspended.status_code == 200
    assert suspended.json()["data"]["status"] == "suspended"
    reactivated = client.patch(f"/api/v1/sa/facilities/{fid}", headers=auth(sa_token), json={"status": "active"})
    assert reactivated.json()["data"]["status"] == "active"


# ═══ الاشتراك والمستخدمون ═══

def test_patch_subscription_seats_and_plan(client, sa_token):
    fid = client.get("/api/v1/sa/facilities?q=الشفاء", headers=auth(sa_token)).json()["data"][0]["id"]
    detail = client.get(f"/api/v1/sa/facilities/{fid}", headers=auth(sa_token)).json()["data"]
    current = detail["subscription"]["seats_total"]

    expanded = client.patch(f"/api/v1/sa/facilities/{fid}/subscription", headers=auth(sa_token),
                            json={"seats_total": current + 2})
    assert expanded.status_code == 200
    assert expanded.json()["data"]["seats_total"] == current + 2

    below_used = client.patch(f"/api/v1/sa/facilities/{fid}/subscription", headers=auth(sa_token),
                              json={"seats_total": 1})
    assert below_used.status_code == 422
    assert below_used.json()["error"]["code"] == "MDF-4221"

    bad_plan = client.patch(f"/api/v1/sa/facilities/{fid}/subscription", headers=auth(sa_token),
                            json={"plan_code": "no-such-plan"})
    assert bad_plan.status_code == 404

    restored = client.patch(f"/api/v1/sa/facilities/{fid}/subscription", headers=auth(sa_token),
                            json={"seats_total": current})
    assert restored.status_code == 200

    events = client.get(f"/api/v1/sa/facilities/{fid}", headers=auth(sa_token)).json()["data"]["seat_events"]
    assert any(event["by_platform"] for event in events)


def test_create_admin_and_toggle_user(client, sa_token):
    fid = client.get("/api/v1/sa/facilities?q=الشفاء", headers=auth(sa_token)).json()["data"][0]["id"]
    created = client.post(f"/api/v1/sa/facilities/{fid}/users", headers=auth(sa_token), json={
        "role": "admin", "full_name": "أدمن إضافي من المنصة", "username": "admin.platform",
        "password": "Passw0rd!x", "email": "extra.admin@example.sa",
    })
    assert created.status_code == 201, created.text
    user_id = created.json()["data"]["id"]

    duplicate = client.post(f"/api/v1/sa/facilities/{fid}/users", headers=auth(sa_token), json={
        "role": "admin", "full_name": "مكرر", "username": "admin.platform",
        "password": "Passw0rd!x", "email": "dup@example.sa",
    })
    assert duplicate.status_code == 404
    assert duplicate.json()["error"]["details"]["reason"] == "username_taken"

    disabled = client.patch(f"/api/v1/sa/users/{user_id}", headers=auth(sa_token), json={"is_active": False})
    assert disabled.status_code == 200
    assert disabled.json()["data"]["is_active"] is False

    reset = client.post(f"/api/v1/sa/users/{user_id}/reset-password", headers=auth(sa_token))
    assert reset.status_code == 200
    assert reset.json()["data"]["temporary_password"].startswith("Md-")


# ═══ الباقات ═══

def test_plans_crud_and_pricing(client, sa_token):
    listing = client.get("/api/v1/sa/plans", headers=auth(sa_token))
    assert listing.status_code == 200
    codes = {plan["code"] for plan in listing.json()["data"]}
    assert {"monthly", "yearly"} <= codes

    created = client.post("/api/v1/sa/plans", headers=auth(sa_token), json={
        "code": "vip-monthly", "name_ar": "كبار المنشآت", "name_en": "VIP",
        "seat_price_sar": "750.00", "billing_cycle": "monthly",
    })
    assert created.status_code == 201, created.text
    plan_id = created.json()["data"]["id"]

    dup = client.post("/api/v1/sa/plans", headers=auth(sa_token), json={
        "code": "vip-monthly", "name_ar": "مكرر", "name_en": "Dup", "seat_price_sar": "10.00",
    })
    assert dup.status_code == 404

    patched = client.patch(f"/api/v1/sa/plans/{plan_id}", headers=auth(sa_token),
                           json={"seat_price_sar": "800.00", "is_active": False})
    assert patched.status_code == 200
    assert patched.json()["data"]["seat_price_sar"] == "800.00"
    assert patched.json()["data"]["is_active"] is False

    # الباقة الموقوفة لا تُسند لمنشأة
    fid = client.get("/api/v1/sa/facilities?q=الشفاء", headers=auth(sa_token)).json()["data"][0]["id"]
    assign = client.patch(f"/api/v1/sa/facilities/{fid}/subscription", headers=auth(sa_token),
                          json={"plan_code": "vip-monthly"})
    assert assign.status_code == 404


# ═══ الفوترة اليدوية ═══

def test_issue_invoice_by_active_doctors_and_settle(client, sa_token):
    fid = client.get("/api/v1/sa/facilities?q=الشفاء", headers=auth(sa_token)).json()["data"][0]["id"]
    detail = client.get(f"/api/v1/sa/facilities/{fid}", headers=auth(sa_token)).json()["data"]
    used = detail["subscription"]["seats_used"]
    price = float(detail["subscription"]["plan_info"]["seat_price_sar"])

    issued = client.post(f"/api/v1/sa/facilities/{fid}/invoices", headers=auth(sa_token), json={})
    assert issued.status_code == 201, issued.text
    invoice = issued.json()["data"]
    assert float(invoice["amount_sar"]) == pytest.approx(used * price)
    assert float(invoice["vat_sar"]) == pytest.approx(used * price * 0.15, abs=0.01)
    assert invoice["status"] == "due"

    paid = client.patch(f"/api/v1/sa/invoices/{invoice['id']}", headers=auth(sa_token), json={"status": "paid"})
    assert paid.status_code == 200
    assert paid.json()["data"]["status"] == "paid"
    assert paid.json()["data"]["provider_ref"].startswith("manual_")

    # لا تراجع عن سداد
    void_paid = client.patch(f"/api/v1/sa/invoices/{invoice['id']}", headers=auth(sa_token), json={"status": "void"})
    assert void_paid.status_code == 422
    assert void_paid.json()["error"]["code"] == "MDF-4228"


def test_manual_settlement_lifts_suspension(client, sa_token):
    """تعليق منشأة + فاتورة متأخرة → تسجيل السداد يدوياً يرفع التعليق."""
    fid = client.get("/api/v1/sa/facilities?q=النخبة", headers=auth(sa_token)).json()["data"][0]["id"]
    issued = client.post(f"/api/v1/sa/facilities/{fid}/invoices", headers=auth(sa_token), json={"seats": 1})
    assert issued.status_code == 201
    invoice_id = issued.json()["data"]["id"]

    overdue = client.patch(f"/api/v1/sa/invoices/{invoice_id}", headers=auth(sa_token), json={"status": "overdue"})
    assert overdue.status_code == 200
    suspended = client.patch(f"/api/v1/sa/facilities/{fid}", headers=auth(sa_token), json={"status": "suspended"})
    assert suspended.json()["data"]["status"] == "suspended"

    paid = client.patch(f"/api/v1/sa/invoices/{invoice_id}", headers=auth(sa_token), json={"status": "paid"})
    assert paid.status_code == 200

    detail = client.get(f"/api/v1/sa/facilities/{fid}", headers=auth(sa_token)).json()["data"]
    assert detail["facility"]["status"] == "active"


def test_all_invoices_listing_with_facility_name(client, sa_token):
    response = client.get("/api/v1/sa/invoices?status=paid", headers=auth(sa_token))
    assert response.status_code == 200
    rows = response.json()["data"]
    assert len(rows) >= 1
    assert all(row["status"] == "paid" for row in rows)
    assert all(row["facility_name"] for row in rows)


# ═══ الحوكمة — الدرجات الخمس (DOC-20 §١.٢) ═══

def _sa_login(client, username: str, password: str, totp_code: str | None = None) -> str:
    body = {"username": username, "password": password}
    if totp_code is not None:
        body["totp_code"] = totp_code
    response = client.post("/api/v1/sa/auth/login", json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]["access_token"]


@pytest.fixture(scope="module")
def finance_token(client, sa_token) -> str:
    created = client.post("/api/v1/sa/admins", headers=auth(sa_token), json={
        "username": "fin.test", "full_name": "محاسب المنصة", "password": "Finance@12345",
        "role": "finance",
    })
    assert created.status_code == 201, created.text
    return _sa_login(client, "fin.test", "Finance@12345")


def test_me_includes_role(client, sa_token):
    me = client.get("/api/v1/sa/me", headers=auth(sa_token)).json()["data"]
    assert me["role"] == "owner"
    assert me["totp_enabled"] is False


def test_finance_grade_limits(client, sa_token, finance_token):
    """finance: فواتير فقط — لا حالة منشأة ولا مستخدمين ولا باقات ولا حسابات."""
    fid = client.get("/api/v1/sa/facilities?q=الشفاء", headers=auth(sa_token)).json()["data"][0]["id"]

    # قراءة مسموحة
    assert client.get("/api/v1/sa/overview", headers=auth(finance_token)).status_code == 200
    assert client.get(f"/api/v1/sa/facilities/{fid}", headers=auth(finance_token)).status_code == 200

    # كتابات محظورة
    for method, path, body in [
        ("PATCH", f"/api/v1/sa/facilities/{fid}", {"status": "suspended"}),
        ("PATCH", f"/api/v1/sa/facilities/{fid}/subscription", {"seats_total": 10}),
        ("POST", "/api/v1/sa/plans", {"code": "x-plan", "name_ar": "تجريبية", "name_en": "XPlan", "seat_price_sar": "1.00"}),
        ("GET", "/api/v1/sa/admins", None),
    ]:
        response = client.request(method, path, headers=auth(finance_token), json=body)
        assert response.status_code == 403, f"{method} {path}: {response.text}"
        assert response.json()["error"]["code"] == "MDF-4031"

    # إصدار فاتورة مسموح للمالية
    issued = client.post(f"/api/v1/sa/facilities/{fid}/invoices", headers=auth(finance_token), json={"seats": 1})
    assert issued.status_code == 201
    voided = client.patch(f"/api/v1/sa/invoices/{issued.json()['data']['id']}",
                          headers=auth(finance_token), json={"status": "void"})
    assert voided.status_code == 200


def test_last_owner_protection(client, sa_token):
    """MDF-4229: لا تخفيض/تعطيل لآخر مالك فعّال."""
    owner_id = next(
        a["id"] for a in client.get("/api/v1/sa/admins", headers=auth(sa_token)).json()["data"]
        if a["username"] == "owner"
    )
    for body in [{"role": "ops"}, {"is_active": False}]:
        response = client.patch(f"/api/v1/sa/admins/{owner_id}", headers=auth(sa_token), json=body)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "MDF-4229"


def test_admin_lifecycle_and_audit_trail(client, sa_token):
    created = client.post("/api/v1/sa/admins", headers=auth(sa_token), json={
        "username": "ops.test", "full_name": "مشغّل المنصة", "password": "Operate@12345",
        "role": "ops",
    })
    assert created.status_code == 201
    admin_id = created.json()["data"]["id"]

    # ops يقدر يعدّل منشأة لكن لا ينشئ باقة
    ops_token = _sa_login(client, "ops.test", "Operate@12345")
    fid = client.get("/api/v1/sa/facilities?q=النخبة", headers=auth(sa_token)).json()["data"][0]["id"]
    assert client.patch(f"/api/v1/sa/facilities/{fid}", headers=auth(ops_token),
                        json={"name": "مستشفى النخبة التخصصي"}).status_code == 200
    assert client.post("/api/v1/sa/plans", headers=auth(ops_token),
                       json={"code": "op-x", "name_ar": "تجريبية", "name_en": "OpsPlan", "seat_price_sar": "1.00"}).status_code == 403

    # تعطيل الحساب ثم رفض دخوله
    disabled = client.patch(f"/api/v1/sa/admins/{admin_id}", headers=auth(sa_token), json={"is_active": False})
    assert disabled.status_code == 200
    login = client.post("/api/v1/sa/auth/login", json={"username": "ops.test", "password": "Operate@12345"})
    assert login.status_code == 403  # MDF-4013

    # السجل الموحّد التقط الأفعال
    audit_rows = client.get("/api/v1/sa/audit?action=sa.admin", headers=auth(sa_token)).json()["data"]
    actions = {row["action"] for row in audit_rows}
    assert "sa.admin_created" in actions
    assert "sa.admin_updated" in actions
    assert all(row["actor"] for row in audit_rows)


def test_platform_audit_filters(client, sa_token):
    fid = client.get("/api/v1/sa/facilities?q=الشفاء", headers=auth(sa_token)).json()["data"][0]["id"]
    rows = client.get(f"/api/v1/sa/audit?facility_id={fid}", headers=auth(sa_token)).json()["data"]
    assert len(rows) >= 1
    assert all(row["facility_id"] == fid for row in rows)
    assert all(row["facility_name"] for row in rows)


# ═══ المصادقة الثنائية 2FA (DOC-20 §١.٣) ═══

def _totp_code(secret: str) -> str:
    import time

    from app.totp import _hotp
    return _hotp(secret, int(time.time() // 30))


def test_2fa_full_lifecycle(client, sa_token):
    """setup → enable → login يتطلب رمزاً → recovery يعمل → reauth للإجراءات الحساسة → disable."""
    # حساب مخصص كي لا يؤثر على جلسات بقية الاختبارات
    created = client.post("/api/v1/sa/admins", headers=auth(sa_token), json={
        "username": "sec.test", "full_name": "أمن المنصة", "password": "Secure@12345",
        "role": "owner",
    })
    assert created.status_code == 201
    token = _sa_login(client, "sec.test", "Secure@12345")

    setup = client.post("/api/v1/sa/me/2fa/setup", headers=auth(token))
    assert setup.status_code == 200
    secret = setup.json()["data"]["secret"]
    assert setup.json()["data"]["otpauth_uri"].startswith("otpauth://totp/")

    # تفعيل برمز خاطئ يرفض
    bad = client.post("/api/v1/sa/me/2fa/enable", headers=auth(token), json={"code": "000000"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "MDF-4015"

    enabled = client.post("/api/v1/sa/me/2fa/enable", headers=auth(token), json={"code": _totp_code(secret)})
    assert enabled.status_code == 200
    recovery_codes = enabled.json()["data"]["recovery_codes"]
    assert len(recovery_codes) == 8

    # الدخول بلا رمز → MDF-4015 · برمز صحيح → ينجح
    no_code = client.post("/api/v1/sa/auth/login", json={"username": "sec.test", "password": "Secure@12345"})
    assert no_code.status_code == 401
    assert no_code.json()["error"]["details"].get("totp_required") is True
    token2 = _sa_login(client, "sec.test", "Secure@12345", _totp_code(secret))

    # إعادة المصادقة للإجراء الحساس: تغيير سعر بلا ترويسة → MDF-4015، بها → ينجح
    plan_id = next(p["id"] for p in client.get("/api/v1/sa/plans", headers=auth(token2)).json()["data"]
                   if p["code"] == "monthly")
    no_reauth = client.patch(f"/api/v1/sa/plans/{plan_id}", headers=auth(token2),
                             json={"seat_price_sar": "450.00"})
    assert no_reauth.status_code == 401
    assert no_reauth.json()["error"]["details"].get("reason") == "reauth_required"
    with_reauth = client.patch(f"/api/v1/sa/plans/{plan_id}",
                               headers={**auth(token2), "X-SA-Reauth": _totp_code(secret)},
                               json={"seat_price_sar": "450.00"})
    assert with_reauth.status_code == 200
    assert with_reauth.json()["data"]["seat_price_sar"] == "450.00"
    # إرجاع السعر
    client.patch(f"/api/v1/sa/plans/{plan_id}",
                 headers={**auth(token2), "X-SA-Reauth": _totp_code(secret)},
                 json={"seat_price_sar": "400.00"})

    # رمز استرداد يدخل مرة واحدة فقط
    token3 = _sa_login(client, "sec.test", "Secure@12345", recovery_codes[0])
    reused = client.post("/api/v1/sa/auth/login", json={
        "username": "sec.test", "password": "Secure@12345", "totp_code": recovery_codes[0],
    })
    assert reused.status_code == 401

    # تعطيل 2FA برمز حي
    disabled = client.post("/api/v1/sa/me/2fa/disable", headers=auth(token3), json={"code": _totp_code(secret)})
    assert disabled.status_code == 200
    _sa_login(client, "sec.test", "Secure@12345")  # يدخل بلا رمز بعد التعطيل
