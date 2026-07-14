"""قيود قاعدة البيانات — DOC-04: آلة الحالات، الإلحاقية، لا رفع بلا اعتماد، ICD10AM، تجميد الأقسام."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError


def _visit_by_state(conn, state: str):
    return conn.execute(text("SELECT id, facility_id FROM visits WHERE state = :s LIMIT 1"), {"s": state}).fetchone()


def test_visit_state_machine_blocks_illegal_transitions(owner_engine):
    """أي انتقال غير معرف يُرفض بـ trigger → MDF-4223 (حتى لمالك القاعدة)."""
    illegal = [
        ("draft", "summarized"), ("draft", "approved"), ("draft", "uploaded"),
        ("uploaded", "in_review"), ("uploaded", "draft"), ("cancelled", "draft"),
        ("in_review", "recording"), ("summarized", "approved"),
    ]
    with owner_engine.connect() as conn:
        for from_state, to_state in illegal:
            row = _visit_by_state(conn, from_state)
            if row is None:
                continue
            with pytest.raises(DBAPIError, match="MDF-4223"):
                with conn.begin_nested():
                    conn.execute(text("UPDATE visits SET state = :to WHERE id = :id"),
                                 {"to": to_state, "id": row.id})


def test_visit_cancelled_only_from_draft_or_recording(owner_engine):
    with owner_engine.connect() as conn:
        row = _visit_by_state(conn, "in_review")
        assert row is not None
        with pytest.raises(DBAPIError, match="MDF-4223"):
            with conn.begin_nested():
                conn.execute(text("UPDATE visits SET state = 'cancelled' WHERE id = :id"), {"id": row.id})


def test_approvals_append_only(owner_engine, app_engine):
    """UPDATE/DELETE على approvals يفشل — trigger يعمل حتى على المالك (NFR-10)."""
    with owner_engine.connect() as conn:
        approval_id = conn.execute(text("SELECT id FROM approvals LIMIT 1")).scalar_one()
        with pytest.raises(DBAPIError, match="append-only"):
            with conn.begin_nested():
                conn.execute(text("UPDATE approvals SET summary_hash = 'tampered' WHERE id = :id"),
                             {"id": approval_id})
        with pytest.raises(DBAPIError, match="append-only"):
            with conn.begin_nested():
                conn.execute(text("DELETE FROM approvals WHERE id = :id"), {"id": approval_id})

    # ودور التطبيق محروم أصلاً من الصلاحية (REVOKE)
    with app_engine.connect() as conn:
        facility = conn.execute(text("SELECT facility_id FROM alembic_version, approvals LIMIT 1"))
        with pytest.raises(DBAPIError):
            with conn.begin_nested():
                conn.execute(text("UPDATE approvals SET summary_hash = 'x'"))


def test_audit_logs_append_only(owner_engine):
    with owner_engine.connect() as conn:
        log_id = conn.execute(text("SELECT id FROM audit_logs LIMIT 1")).scalar_one()
        with pytest.raises(DBAPIError, match="append-only"):
            with conn.begin_nested():
                conn.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": log_id})


def test_upload_job_requires_approval_fk(owner_engine):
    """إنشاء upload_job بلا اعتماد → يفشل بقيد FK (FR-803 على مستوى القاعدة)."""
    with owner_engine.connect() as conn:
        row = conn.execute(text(
            "SELECT v.id, v.facility_id FROM visits v "
            "LEFT JOIN approvals a ON a.visit_id = v.id WHERE a.id IS NULL LIMIT 1"
        )).fetchone()
        assert row is not None
        with pytest.raises(IntegrityError):
            with conn.begin_nested():
                conn.execute(text(
                    "INSERT INTO upload_jobs (id, visit_id, facility_id, status, attempts_count, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), :v, :f, 'queued', 0, now(), now())"
                ), {"v": row.id, "f": row.facility_id})


def test_icd10am_cannot_be_disabled(owner_engine):
    """CHECK يمنع تعطيل ICD10AM (قرار مالك 2026-07-14)."""
    with owner_engine.connect() as conn:
        with pytest.raises(IntegrityError, match="ck_icd10am_always_active"):
            with conn.begin_nested():
                conn.execute(text("UPDATE coding_system_configs SET is_active = false WHERE system = 'ICD10AM'"))
        conn.rollback()
        # ACHI قابل للتعطيل ثم يُعاد
        with conn.begin():
            conn.execute(text("UPDATE coding_system_configs SET is_active = false WHERE system = 'ACHI'"))
            conn.execute(text("UPDATE coding_system_configs SET is_active = true WHERE system = 'ACHI'"))


def test_summary_sections_frozen_after_approval(owner_engine):
    """منع تعديل summary_sections بعد الاعتماد (MDF-4226) — trigger."""
    with owner_engine.connect() as conn:
        section_id = conn.execute(text(
            "SELECT sec.id FROM summary_sections sec "
            "JOIN summaries s ON s.id = sec.summary_id "
            "JOIN approvals a ON a.visit_id = s.visit_id LIMIT 1"
        )).scalar_one()
        with pytest.raises(DBAPIError, match="MDF-4226"):
            with conn.begin_nested():
                conn.execute(text("UPDATE summary_sections SET content_current = 'tampered' WHERE id = :id"),
                             {"id": section_id})


def test_two_roles_only_check(owner_engine):
    with owner_engine.connect() as conn:
        with pytest.raises((IntegrityError, DBAPIError)):
            with conn.begin_nested():
                conn.execute(text(
                    "INSERT INTO users (id, facility_id, role, full_name, username, password_hash, is_active, created_at, updated_at) "
                    "SELECT gen_random_uuid(), id, 'superuser', 'x', 'x', 'x', true, now(), now() FROM facilities LIMIT 1"
                ))


def test_pii_columns_encrypted_at_rest(owner_engine):
    """أعمدة PII والنصوص السريرية مشفّرة عموداً — القيمة الخام لا تظهر في التخزين."""
    with owner_engine.connect() as conn:
        raw_name = conn.execute(text("SELECT display_name FROM patients LIMIT 1")).scalar_one()
        assert raw_name.startswith("enc:v1:"), "أسماء المرضى يجب أن تكون مشفرة في التخزين"
        raw_content = conn.execute(text("SELECT content_current FROM summary_sections LIMIT 1")).scalar_one()
        assert raw_content.startswith("enc:v1:"), "النص السريري يجب أن يكون مشفراً في التخزين"
        raw_transcript = conn.execute(text("SELECT content_json FROM transcripts LIMIT 1")).scalar_one()
        assert str(raw_transcript).startswith("enc:v1:")
