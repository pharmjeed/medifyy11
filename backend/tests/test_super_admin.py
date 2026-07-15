"""اختبارات طبقة السوبر أدمن /sa — المصادقة والعزل والباقات والفوترة اليدوية."""
from __future__ import annotations

import pytest

from .conftest import auth


@pytest.fixture(scope="module")
def sa_token(client) -> str:
    response = client.post("/api/v1/sa/auth/login", json={"username": "owner", "password": "Owner@12345"})
    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["admin"]["role"] == "super_admin"
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
