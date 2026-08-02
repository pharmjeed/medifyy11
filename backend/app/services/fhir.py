"""حزمة الرفع FHIR متوافقة NPHIES — DOC-05 §٦ + دلالة الاستبدال (م6/م7).

Bundle من نوع transaction يضم Encounter + Composition (SOAP) + DocumentReference
+ Condition[] + MedicationRequest[] + Procedure[] — كل مدخل بحقل request صالح R4.

دلالة الاستبدال (المبدأ 2): النسخة ≥2 → Composition.status="amended" +
DocumentReference.relatesTo[code="replaces"] يشير بمعرّف وثيقة Medify السابقة
حصراً (urn:medify:doc:{visit}:{n-1}) — لا يمس أي وثيقة أخرى بملف المريض.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import GuidanceItem, Patient, Summary, SummarySection, Visit


def medify_doc_identifier(visit_id: uuid.UUID | str, version_number: int) -> str:
    """معرّف وثيقة Medify الثابت لكل نسخة — مرجع relatesTo/replaces وMSH-10 (م7)."""
    return f"urn:medify:doc:{visit_id}:{version_number}"


def bundle_hash(bundle: dict[str, Any]) -> str:
    """بصمة الحزمة (canonical JSON) — تُخزَّن مع النسخة (note_versions.bundle_hash)."""
    canonical = json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _entry(resource: dict[str, Any], if_none_exist: str | None = None) -> dict[str, Any]:
    """مدخل transaction صالح R4 — POST + ifNoneExist (conditional create — م7):
    إعادة الإرسال بنفس المعرّف الثابت لا تنشئ موارد مكررة لدى خادم متوافق."""
    request: dict[str, Any] = {"method": "POST", "url": resource["resourceType"]}
    if if_none_exist:
        request["ifNoneExist"] = if_none_exist
    return {"resource": resource, "request": request}


def build_bundle(db: Session, visit: Visit, version_number: int | None = None) -> dict[str, Any]:
    """version_number يقود دلالة الاستبدال — None = الدورة الحالية للزيارة."""
    version = version_number if version_number is not None else visit.cycle
    patient = db.execute(select(Patient).where(Patient.id == visit.patient_id)).scalar_one()
    summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one()
    sections = db.execute(
        select(SummarySection).where(SummarySection.summary_id == summary.id).order_by(SummarySection.position)
    ).scalars().all()

    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    encounter_id = f"encounter-{visit.id}"
    doc_identifier = medify_doc_identifier(visit.id, version)
    composition_sections = [
        {
            "title": section.section_key,
            "text": {"status": "generated", "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">{section.content_current}</div>"},
        }
        for section in sections
    ]

    conditions: list[dict[str, Any]] = []
    medication_requests: list[dict[str, Any]] = []
    procedures: list[dict[str, Any]] = []
    for section in sections:
        items = db.execute(
            select(GuidanceItem).where(
                GuidanceItem.section_id == section.id,
                GuidanceItem.status.in_(["accepted", "modified"]),
            )
        ).scalars().all()
        for item in items:
            coding = {
                "system": f"urn:medify:coding:{item.code_system}",
                "code": item.code_value or "",
                "display": item.suggestion_text,
            }
            resource_common = {"subject": {"reference": f"Patient/{patient.hospital_mrn}"}}
            if item.kind in ("clinical_dx", "coding_match"):
                conditions.append({
                    "resourceType": "Condition",
                    "id": f"condition-{item.id}",
                    "code": {"coding": [coding]},
                    "encounter": {"reference": f"Encounter/{encounter_id}"},
                    **resource_common,
                })
            elif item.kind == "clinical_rx":
                medication_requests.append({
                    "resourceType": "MedicationRequest",
                    "id": f"medreq-{item.id}",
                    "status": "active",
                    "intent": "proposal",
                    "medicationCodeableConcept": {"coding": [coding]},
                    **resource_common,
                })
            elif item.kind == "clinical_procedure":
                procedures.append({
                    "resourceType": "Procedure",
                    "id": f"procedure-{item.id}",
                    "status": "preparation",
                    "code": {"coding": [coding]},
                    **resource_common,
                })

    composition = {
        "resourceType": "Composition",
        "id": f"composition-{visit.id}-v{version}",
        # النسخة ≥2 = تعديل معتمد يستبدل سابقه — الدلالة القياسية amended (م6)
        "status": "final" if version <= 1 else "amended",
        "type": {"coding": [{"system": "http://loinc.org", "code": "11488-4", "display": "Consult note"}]},
        "title": "Medify SOAP Summary",
        "date": now_iso,
        "section": composition_sections,
    }

    document_reference: dict[str, Any] = {
        "resourceType": "DocumentReference",
        "id": f"docref-{visit.id}-v{version}",
        "status": "current",
        "masterIdentifier": {"system": "urn:medify:doc", "value": doc_identifier},
        "type": {"coding": [{"system": "http://loinc.org", "code": "11488-4", "display": "Consult note"}]},
        "subject": {"reference": f"Patient/{patient.hospital_mrn}"},
        "date": now_iso,
        "description": f"Medify visit note v{version}",
        "content": [{
            "attachment": {
                "contentType": "application/fhir+json",
                "title": f"Medify SOAP Summary v{version}",
            }
        }],
        "context": {"encounter": [{"reference": f"Encounter/{encounter_id}"}]},
    }
    if version >= 2:
        # قاعدة عدم التصادم: الاستبدال يستهدف وثيقة Medify السابقة حصراً بمعرّفها المباشر —
        # إضافات موظفي المستشفى وثائق مستقلة لا يمسها الاستبدال (integration-spec §الاستبدال)
        document_reference["relatesTo"] = [{
            "code": "replaces",
            "target": {"identifier": {"system": "urn:medify:doc",
                                      "value": medify_doc_identifier(visit.id, version - 1)}},
        }]

    entries: list[dict[str, Any]] = [
        _entry({
            "resourceType": "Encounter",
            "id": encounter_id,
            "status": "finished",
            "class": {"code": "AMB"},
            "subject": {"reference": f"Patient/{patient.hospital_mrn}"},
        }, if_none_exist=f"identifier=urn:medify:encounter|{visit.id}"),
        _entry(composition, if_none_exist=f"identifier=urn:medify:composition|{visit.id}:{version}"),
        _entry(document_reference, if_none_exist=f"identifier=urn:medify:doc|{doc_identifier}"),
    ]
    entries += [
        _entry(resource, if_none_exist=f"identifier=urn:medify:item|{resource['id']}:v{version}")
        for resource in conditions + medication_requests + procedures
    ]

    return {
        "resourceType": "Bundle",
        "id": f"medify-visit-{visit.id}-v{version}",
        "type": "transaction",
        "timestamp": now_iso,
        "entry": entries,
    }


def store_bundle(visit_id: uuid.UUID, bundle: dict[str, Any], version_number: int = 1) -> str:
    """يُخزَّن مرجع الحزمة (fhir_payload_ref) لكل نسخة — يُبنى وقت الاعتماد بسياق الدكتور (D-19)."""
    base = Path(get_settings().recordings_dir).parent / "fhir"
    base.mkdir(parents=True, exist_ok=True)
    suffix = f".v{version_number}" if version_number > 1 else ""
    path = base / f"{visit_id}{suffix}.json"
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(path)
