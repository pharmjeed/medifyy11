"""اختبار العزل الآلي — DOC-17 §١: منشأة A تقرأ بيانات B → يفشل، بلا استثناء.
الطبقات الثلاث: API guard → RLS (على اتصال medify_app) → قيود القاعدة."""
from __future__ import annotations

from sqlalchemy import text

from tests.conftest import auth


def _first_visit_id(client, doctor_token) -> str:
    visits = client.get("/api/v1/visits", headers=auth(doctor_token)).json()["data"]
    assert visits
    return visits[0]["id"]


def test_cross_facility_doctors_list_isolated(client, admin_token, foreign_admin_token):
    mine = client.get("/api/v1/doctors", headers=auth(admin_token)).json()["data"]
    theirs = client.get("/api/v1/doctors", headers=auth(foreign_admin_token)).json()["data"]
    my_usernames = {d["username"] for d in mine}
    their_usernames = {d["username"] for d in theirs}
    assert "dr.ahmad" in my_usernames and "dr.ahmad" not in their_usernames
    assert "dr.salem" in their_usernames and "dr.salem" not in my_usernames


def test_cross_facility_patients_isolated(client, doctor_token, foreign_doctor_token):
    mine = client.get("/api/v1/patients", headers=auth(doctor_token), params={"per_page": 100}).json()
    theirs = client.get("/api/v1/patients", headers=auth(foreign_doctor_token), params={"per_page": 100}).json()
    my_mrns = {p["hospital_mrn"] for p in mine["data"]}
    their_mrns = {p["hospital_mrn"] for p in theirs["data"]}
    assert "1042376" in my_mrns and "1042376" not in their_mrns
    assert my_mrns.isdisjoint(their_mrns)
    assert mine["meta"]["total"] == 20  # 20 مريضاً متزامناً (CLAUDE-CODE-PROMPT §٢)


def test_foreign_doctor_cannot_read_visit_mdf4041(client, doctor_token, foreign_doctor_token):
    visit_id = _first_visit_id(client, doctor_token)
    for path in (f"/api/v1/visits/{visit_id}/summary",
                 f"/api/v1/visits/{visit_id}/transcript",
                 f"/api/v1/visits/{visit_id}/upload-status"):
        response = client.get(path, headers=auth(foreign_doctor_token))
        assert response.status_code == 404, path  # لا كشف عن وجود المورد (DOC-06 §٤)
        assert response.json()["error"]["code"] == "MDF-4041"


def test_same_facility_other_doctor_cannot_read_visit(client, doctor_token, doctor2_same_facility_token):
    """دكتور يحاول زيارة دكتور آخر → يفشل (DOC-06: doctor_id = self)."""
    visit_id = _first_visit_id(client, doctor_token)
    response = client.get(f"/api/v1/visits/{visit_id}/summary", headers=auth(doctor2_same_facility_token))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MDF-4041"

    own_visits = client.get("/api/v1/visits", headers=auth(doctor2_same_facility_token)).json()["data"]
    assert own_visits == []  # كل زيارات seed لدكتور أحمد


def test_admin_cannot_read_clinical_content(client, admin_token, doctor_token):
    """الأدمن لا يقرأ محتوى سريرياً نصياً أبداً (DOC-06 — الفصل الجوهري)."""
    visit_id = _first_visit_id(client, doctor_token)
    for path in (f"/api/v1/visits/{visit_id}/summary", f"/api/v1/visits/{visit_id}/transcript"):
        response = client.get(path, headers=auth(admin_token))
        assert response.status_code == 403, path
        assert response.json()["error"]["code"] == "MDF-4031"
    # ولا يبحث في المرضى (DOC-06 §٣)
    response = client.get("/api/v1/patients", headers=auth(admin_token))
    assert response.status_code == 403


def test_rls_blocks_cross_facility_at_database_level(app_engine, owner_engine):
    """الطبقة الثانية مباشرة: اتصال medify_app بسياق منشأة A لا يرى صفوف B إطلاقاً."""
    with owner_engine.connect() as conn:
        facility_a, facility_b = [
            row[0] for row in conn.execute(text(
                "SELECT id FROM facilities ORDER BY commercial_reg"
            )).fetchall()
        ]
        total_users = conn.execute(text("SELECT count(*) FROM users")).scalar_one()

    with app_engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.facility_id', :f, false)"), {"f": str(facility_a)})
        conn.execute(text("SELECT set_config('app.user_role', 'admin', false)"))
        visible_users = conn.execute(text("SELECT count(*) FROM users")).scalar_one()
        foreign_users = conn.execute(text(
            "SELECT count(*) FROM users WHERE facility_id = :b"
        ), {"b": str(facility_b)}).scalar_one()
        assert foreign_users == 0, "RLS يجب أن يحجب صفوف المنشأة الأخرى"
        assert 0 < visible_users < total_users

        for table in ("patients", "visits", "transcripts", "summaries", "summary_sections",
                      "guidance_items", "approvals", "upload_jobs", "audit_logs", "notifications",
                      "invoices", "templates", "clinics"):
            foreign_rows = conn.execute(text(
                f"SELECT count(*) FROM {table} WHERE facility_id = :b"
            ), {"b": str(facility_b)}).scalar_one()
            assert foreign_rows == 0, f"تسريب عبر {table}"


def test_rls_no_context_means_no_rows(app_engine):
    """بلا سياق منشأة (current_setting فارغ) → صفر صفوف — أمان افتراضي."""
    with app_engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM patients")).scalar_one()
        assert count == 0


def test_rls_admin_blocked_from_clinical_tables(app_engine, owner_engine):
    """الأدمن (بسياق RLS admin) محجوب كلياً عن جداول المحتوى السريري."""
    with owner_engine.connect() as conn:
        facility_a = conn.execute(text(
            "SELECT id FROM facilities WHERE commercial_reg = '1010456789'"
        )).scalar_one()
    with app_engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.facility_id', :f, false)"), {"f": str(facility_a)})
        conn.execute(text("SELECT set_config('app.user_role', 'admin', false)"))
        for table in ("transcripts", "summaries", "summary_sections", "guidance_items", "patients"):
            count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            assert count == 0, f"الأدمن يجب ألا يرى {table}"
        # لكنه يرى الزيارات (صفوف وصفية) ومهام الرفع للوحاته
        assert conn.execute(text("SELECT count(*) FROM visits")).scalar_one() > 0
        assert conn.execute(text("SELECT count(*) FROM upload_jobs")).scalar_one() > 0
