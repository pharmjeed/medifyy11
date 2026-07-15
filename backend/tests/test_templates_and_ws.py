"""القوالب (بناء عكسي/معاينة/حفظ/افتراضي) + بروتوكول WebSocket للتفريغ — FR-500 / DOC-05 §٥."""
from __future__ import annotations

from tests.conftest import auth


# PNG صالح 1×1 بكسل (base64) — كافٍ للتحقق من مسار المرفق دون رفع ملف كبير
PNG_1X1 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def test_reverse_build_generates_structure(client, doctor_token):
    response = client.post("/api/v1/templates/reverse-build", headers=auth(doctor_token), json={
        "sample_text": "S: Follow-up of T2DM and HTN. Reviewed adherence.\nO: BP 150/95.\n"
                       "A: 1. HTN uncontrolled. 2. T2DM.\nP: Continue metformin; recheck BP in 2 weeks.\n"
                       "E: Advised daily home BP logging.",
    })
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["structure"]["sections"], "بنية مولدة — لا تُحفظ تلقائياً (FR-502)"
    assert data["name"]


def test_reverse_build_from_attached_image(client, doctor_token):
    """يكفي مرفق صورة بلا نص — النموذج يقرأ المثال من المرفق (FR-502)."""
    response = client.post("/api/v1/templates/reverse-build", headers=auth(doctor_token), json={
        "sample_file": {"media_type": "image/png", "data": PNG_1X1, "filename": "note.png"},
    })
    assert response.status_code == 200, response.text
    assert response.json()["data"]["structure"]["sections"]


def test_reverse_build_requires_text_or_file(client, doctor_token):
    """لا نص ولا مرفق → تحقق فاشل يُغلَّف بـ MDF-5001 (D-25)."""
    response = client.post("/api/v1/templates/reverse-build", headers=auth(doctor_token), json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MDF-5001"


def test_reverse_build_rejects_unsupported_media(client, doctor_token):
    response = client.post("/api/v1/templates/reverse-build", headers=auth(doctor_token), json={
        "sample_file": {"media_type": "application/zip", "data": PNG_1X1},
    })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MDF-5001"


def test_preview_then_save_personal_template(client, doctor_token):
    headers = auth(doctor_token)
    build = client.post("/api/v1/templates/reverse-build", headers=headers, json={
        "sample_text": "S: chronic disease follow-up example with adherence review and vitals.",
    }).json()["data"]

    preview = client.post("/api/v1/templates/preview", headers=headers,
                          json={"structure": build["structure"]})
    assert preview.status_code == 200
    assert preview.json()["data"]["sections"]

    saved = client.post("/api/v1/templates", headers=headers, json={
        "name": "متابعة أمراض مزمنة — مركّز",
        "structure": build["structure"],
        "origin": "reverse_built",
        "source_sample_text": "S: chronic disease follow-up example.",
    })
    assert saved.status_code == 201
    template = saved.json()["data"]
    assert template["origin"] == "reverse_built"
    assert template["is_personal"] is True

    default = client.patch(f"/api/v1/templates/{template['id']}/default", headers=headers)
    assert default.status_code == 200
    assert default.json()["data"]["is_default"] is True

    deleted = client.delete(f"/api/v1/templates/{template['id']}", headers=headers)
    assert deleted.json()["data"]["archived"] is True


def test_save_invalid_structure_mdf4225(client, doctor_token):
    response = client.post("/api/v1/templates", headers=auth(doctor_token), json={
        "name": "قالب ناقص",
        "structure": {"sections": [{"section_key": "S", "title": "بلا تعليمات"}]},
        "origin": "reverse_built",
    })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MDF-4225"


def test_doctor_cannot_edit_shared_template(client, doctor_token):
    headers = auth(doctor_token)
    shared = [t for t in client.get("/api/v1/templates", headers=headers).json()["data"] if not t["is_personal"]]
    response = client.patch(f"/api/v1/templates/{shared[0]['id']}", headers=headers, json={"name": "عبث"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "MDF-4031"


def test_websocket_transcribe_protocol(client, doctor_token):
    """partial أثناء البث → final بطوابع زمنية → resume_from عند فجوة → status عند الإنهاء."""
    headers = auth(doctor_token)
    patients = client.get("/api/v1/patients", headers=headers).json()["data"]
    templates = client.get("/api/v1/templates", headers=headers).json()["data"]
    visit = client.post("/api/v1/visits", headers=headers, json={
        "patient_id": patients[0]["id"], "template_id": templates[0]["id"],
    }).json()["data"]
    visit_id = visit["id"]
    client.post(f"/api/v1/visits/{visit_id}/recording/start", headers=headers)

    with client.websocket_connect(f"/ws/visits/{visit_id}/transcribe?token={doctor_token}") as ws:
        got_partial = got_final = False
        for seq in range(8):  # جملتان من المولد التجريبي
            ws.send_json({"type": "audio_chunk", "seq": seq, "payload": "AAAA"})
            message = ws.receive_json()
            if message["type"] == "partial":
                got_partial = True
            elif message["type"] == "final":
                got_final = True
                assert "t0" in message and "t1" in message and message["segment_id"]
                # إسناد المتحدث يُبثّ مع كل مقطع نهائي
                assert message["speaker"] in ("doctor", "patient")
                assert 0.0 <= message["speaker_confidence"] <= 1.0
        assert got_partial and got_final

        # فجوة تسلسل → الخادم يطلب الإعادة من آخر مؤكد (NFR-09)
        ws.send_json({"type": "audio_chunk", "seq": 99, "payload": "AAAA"})
        resume = ws.receive_json()
        assert resume["type"] == "resume_from"
        assert resume["seq"] == 8

        ws.send_json({"type": "pause"})
        assert ws.receive_json()["state"] == "paused"
        ws.send_json({"type": "resume"})
        assert ws.receive_json()["state"] == "recording"

        ws.send_json({"type": "end"})
        assert ws.receive_json() == {"type": "status", "state": "summarizing"}

    # المقاطع حُفظت مرتبطة بالزيارة
    stopped = client.post(f"/api/v1/visits/{visit_id}/recording/stop", headers=headers,
                          json={"duration_sec": 10})
    assert stopped.status_code == 200
    transcript = client.get(f"/api/v1/visits/{visit_id}/transcript", headers=headers).json()["data"]
    assert transcript["content"]["segments"]


def test_websocket_rejects_wrong_state(client, doctor_token):
    headers = auth(doctor_token)
    visits = client.get("/api/v1/visits", headers=headers, params={"state": "uploaded"}).json()["data"]
    from starlette.websockets import WebSocketDisconnect
    import pytest
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/visits/{visits[0]['id']}/transcribe?token={doctor_token}") as ws:
            ws.receive_json()
