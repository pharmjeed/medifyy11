"""محوّل HL7 v2 مصغّر — رسائل MDM عبر MLLP للأنظمة القديمة (م6/م7).

INTEGRATION_ENGINE=hl7 مع endpoint_url بصيغة mllp://host:port.
- أول نقل لنسخة الزيارة: MDM^T02 (وثيقة أصلية).
- الاستبدال (نسخة ≥2 بعد reopen): MDM^T09 — TXA-13 يحمل معرّف وثيقة Medify
  السابقة حصراً (قاعدة عدم التصادم: لا يمس أي وثيقة أخرى بالملف).
- MSH-10 = مفتاح idempotency الواعي بالنسخة "{visit_id}:{version}" (م7) —
  النظام المستقبِل يرفض/يتجاهل التكرار بنفس معرّف الرسالة.
"""
from __future__ import annotations

import datetime as dt
import socket
from urllib.parse import urlparse

VT = b"\x0b"   # بداية كتلة MLLP
FS = b"\x1c"   # نهاية كتلة
CR = b"\x0d"

_FIELD = "|"
_ESCAPES = str.maketrans({"|": "\\F\\", "^": "\\S\\", "~": "\\R\\", "\\": "\\E\\", "&": "\\T\\"})


def _hl7_escape(value: str) -> str:
    return (value or "").translate(_ESCAPES).replace("\r", " ").replace("\n", " ")


def _now_ts() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")


def build_mdm(
    *,
    control_id: str,
    event: str,  # T02 أول نقل | T09 استبدال
    patient_mrn: str,
    patient_name: str,
    doctor_name: str,
    doc_identifier: str,
    parent_doc_identifier: str | None,
    note_text: str,
    facility_name: str = "MEDIFY",
) -> str:
    """رسالة MDM دنيا صالحة: MSH + EVN + PID + TXA + OBX (النص كاملاً)."""
    assert event in ("T02", "T09", "T10"), event
    ts = _now_ts()
    segments = [
        _FIELD.join([
            "MSH", "^~\\&", "MEDIFY", _hl7_escape(facility_name), "HIS", "HIS",
            ts, "", f"MDM^{event}", _hl7_escape(control_id), "P", "2.5",
        ]),
        _FIELD.join(["EVN", event, ts]),
        _FIELD.join(["PID", "1", "", _hl7_escape(patient_mrn), "", _hl7_escape(patient_name)]),
        _FIELD.join([
            "TXA", "1", "CN",  # Consultation note
            "TX", ts, _hl7_escape(doctor_name), "", "", "", "", "",
            "", _hl7_escape(doc_identifier),                     # TXA-12 معرّف الوثيقة الفريد
            _hl7_escape(parent_doc_identifier or ""),            # TXA-13 الوثيقة الأم (الاستبدال)
            "", "", "AU",                                        # TXA-17 authenticated (بوابتان)
        ]),
    ]
    # النص سطر OBX لكل فقرة — TX بسيط تقبله الأنظمة القديمة
    for index, line in enumerate(filter(None, note_text.split("\n")), start=1):
        segments.append(_FIELD.join(["OBX", str(index), "TX", "NOTE", "", _hl7_escape(line)]))
    return "\r".join(segments) + "\r"


def parse_mllp_target(endpoint_url: str) -> tuple[str, int]:
    parsed = urlparse(endpoint_url)
    if parsed.scheme != "mllp" or not parsed.hostname or not parsed.port:
        raise ValueError(f"عنوان MLLP غير صالح: {endpoint_url} — الصيغة mllp://host:port")
    return parsed.hostname, parsed.port


def send_mllp(host: str, port: int, message: str, timeout: float = 30.0) -> tuple[bool, str]:
    """إرسال بتغليف MLLP وقراءة ACK — النجاح = MSA|AA (أو CA). يعيد (نجاح، كود/تفصيل)."""
    framed = VT + message.encode("utf-8") + FS + CR
    with socket.create_connection((host, port), timeout=timeout) as conn:
        conn.sendall(framed)
        buffer = b""
        while FS not in buffer:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buffer += chunk
    ack = buffer.strip(VT + FS + CR).decode("utf-8", errors="replace")
    for segment in ack.split("\r"):
        if segment.startswith("MSA"):
            fields = segment.split(_FIELD)
            code = fields[1] if len(fields) > 1 else ""
            return code in ("AA", "CA"), code
    return False, "no_msa"
