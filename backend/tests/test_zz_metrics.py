"""المرحلة 15 — القياس الآلي: أحداث بأرقام فقط + تجميع ليلي يطابق الحساب اليدوي.

معايير القبول: دورة كاملة → كل الأحداث بأرقام صحيحة | اختبار آلي يفشل إن وُجد
حقل نصي حر في numeric_payload | المجمّع يطابق الحساب اليدوي.
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.conftest import auth, record_consent


def _full_cycle(client, headers, patient_id: str) -> str:
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    created = client.post("/api/v1/visits", headers=headers,
                          json={"patient_id": patient_id, "template_id": templates[0]["id"]})
    assert created.status_code == 201, created.text
    visit_id = created.json()["data"]["id"]
    record_consent(client, visit_id, headers)
    assert client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers).status_code == 200
    assert client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                       json={"duration_sec": 30}).status_code == 200
    summary = client.get(f"/api/v1/visits/{visit_id}/summary", headers=headers).json()["data"]
    # تعديل نصي فعلي — كي تكون درجة edit_distance غير صفرية
    section = summary["sections"][0]
    client.patch(f"/api/v1/summary-sections/{section['id']}",
                 headers={**headers, "If-Match": summary["etag"]},
                 json={"content_current": section["content_current"] + " Extra clinician sentence added."})
    for s in summary["sections"]:
        for item in s["guidance"]:
            if item["status"] != "pending":
                continue
            if item["kind"] in ("clinical_dx", "coding_match") and not item["requires_doctor_input"]:
                client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers,
                             json={"status": "accepted"})
            else:
                client.patch(f"/api/v1/guidance-items/{item['id']}", headers=headers,
                             json={"status": "rejected"})
    assert client.post(f"/api/v1/visits/{visit_id}/note-approve", headers=headers).status_code == 200
    approved = client.post(f"/api/v1/visits/{visit_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    return visit_id


@pytest.fixture(scope="module")
def metrics_visit(client, doctor_token) -> dict:
    headers = auth(doctor_token)
    created = client.post("/api/v1/patients", headers=headers,
                          json={"hospital_mrn": "9900811", "display_name": "مريض القياس"})
    assert created.status_code == 201, created.text
    visit_id = _full_cycle(client, headers, created.json()["data"]["id"])
    return {"visit_id": visit_id, "headers": headers, "patient_id": created.json()["data"]["id"]}


def test_numeric_payload_rejects_non_numeric_values():
    """الحارس التطبيقي: أي قيمة غير رقمية (نص/بوليان) مرفوضة — لا تسرّب محتوى."""
    from app.services.metrics import _assert_numeric

    assert _assert_numeric({"a": 1, "b": 2.5}) == {"a": 1.0, "b": 2.5}
    with pytest.raises(ValueError, match="الأرقام فقط"):
        _assert_numeric({"note": "نص سريري"})
    with pytest.raises(ValueError, match="الأرقام فقط"):
        _assert_numeric({"flag": True})


def test_no_free_text_in_stored_events(metrics_visit, owner_engine):
    """فحص آلي على المخزَّن فعلاً: كل قيم numeric_payload أرقام."""
    with owner_engine.connect() as conn:
        rows = conn.execute(text("SELECT event_type, numeric_payload FROM metric_events")).fetchall()
    assert rows, "الدورة الكاملة دوّنت أحداثاً"
    for event_type, payload in rows:
        assert isinstance(payload, dict)
        for key, value in payload.items():
            assert isinstance(value, (int, float)) and not isinstance(value, bool), \
                f"{event_type}.{key} ليس رقماً: {value!r}"


def test_full_cycle_records_expected_events(metrics_visit, owner_engine):
    visit_id = metrics_visit["visit_id"]
    with owner_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT event_type, numeric_payload FROM metric_events WHERE visit_id = :v"
        ), {"v": visit_id}).fetchall()
    by_type = {event_type: payload for event_type, payload in rows}
    assert {"visit.edit_distance", "visit.guidance_rates", "visit.turnaround",
            "visit.claim_readiness"} <= set(by_type)

    edit = by_type["visit.edit_distance"]
    assert 0.0 < edit["overall"] <= 1.0, "التعديل النصي انعكس في الدرجة"
    assert any(key.startswith("section_") for key in edit), "درجة لكل قسم"

    rates = by_type["visit.guidance_rates"]
    assert abs(rates["accepted_rate"] + rates["rejected_rate"] + rates["modified_rate"] - 1.0) < 0.01

    turnaround = by_type["visit.turnaround"]
    assert turnaround["review_ms"] >= 0
    assert "stop_to_final_approval_ms" in turnaround

    assert by_type["visit.claim_readiness"]["first_pass"] in (0.0, 1.0)


def test_word_level_edit_distance_normalization():
    from app.services.metrics import normalized_edit_distance, word_levenshtein

    assert word_levenshtein("a b c", "a b c") == 0
    assert word_levenshtein("a b c", "a x c") == 1
    assert word_levenshtein("a b", "a b c d") == 2
    assert normalized_edit_distance("a b c d", "a b c d") == 0.0
    assert normalized_edit_distance("a b c d", "w x y z") == 1.0
    assert normalized_edit_distance("a b c d", "a b c z") == 0.25


def test_daily_aggregate_matches_manual_computation(metrics_visit, owner_engine):
    """المجمّع = المتوسط اليدوي لأحداث اليوم، والاستعلام الإداري يقرأ منه."""
    from app.services.metrics import aggregate_daily_metrics

    today = dt.datetime.now(dt.timezone.utc).date()
    with Session(owner_engine) as db:
        result = aggregate_daily_metrics(db, today)
        db.commit()
    assert result["events"] > 0 and result["slices"] > 0

    with owner_engine.connect() as conn:
        manual = conn.execute(text(
            "SELECT avg((numeric_payload->>'overall')::float), count(*) "
            "FROM metric_events WHERE event_type = 'visit.edit_distance' "
            "AND created_at::date = :day"
        ), {"day": today}).fetchone()
        aggregated = conn.execute(text(
            "SELECT average, samples FROM daily_metrics WHERE day = :day AND dimension = 'facility' "
            "AND metric = 'visit.edit_distance.overall'"
        ), {"day": today}).fetchone()
    assert aggregated is not None
    assert aggregated.samples == manual[1]
    assert abs(aggregated.average - float(manual[0])) < 1e-6, "المجمّع يطابق الحساب اليدوي"


def test_admin_summary_endpoint_rbac_and_numbers(client, doctor_token, admin_token, metrics_visit):
    admin_headers = auth(admin_token)
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    body = client.get("/api/v1/admin/metrics/summary", headers=admin_headers,
                      params={"date_from": today, "date_to": today, "group_by": "physician"})
    assert body.status_code == 200, body.text
    data = body.json()["data"]
    assert data["group_by"] == "physician"
    assert data["groups"], "التجميع يحمل شرائح"
    for metrics in data["groups"].values():
        for values in metrics.values():
            assert isinstance(values["samples"], int)
            assert isinstance(values["average"], (int, float))

    forbidden = client.get("/api/v1/admin/metrics/summary", headers=auth(doctor_token))
    assert forbidden.status_code == 403


def test_reopen_records_metric(client, metrics_visit, owner_engine):
    headers = metrics_visit["headers"]
    visit_id = metrics_visit["visit_id"]
    assert client.post(f"/api/v1/visits/{visit_id}/reopen", headers=headers,
                       json={"reason": "قياس reopen"}).status_code == 200
    with owner_engine.connect() as conn:
        payload = conn.execute(text(
            "SELECT numeric_payload FROM metric_events "
            "WHERE visit_id = :v AND event_type = 'visit.reopened'"
        ), {"v": visit_id}).scalar_one()
    assert payload["version"] == 2.0
