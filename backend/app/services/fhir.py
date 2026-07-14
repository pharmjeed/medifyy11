"""حزمة الرفع FHIR متوافقة NPHIES — DOC-05 §٦: Bundle يضم
Encounter + Composition (SOAP) + Condition[] + MedicationRequest[] + Procedure[]."""
from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import GuidanceItem, Patient, Summary, SummarySection, Visit


def build_bundle(db: Session, visit: Visit) -> dict[str, Any]:
    patient = db.execute(select(Patient).where(Patient.id == visit.patient_id)).scalar_one()
    summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one()
    sections = db.execute(
        select(SummarySection).where(SummarySection.summary_id == summary.id).order_by(SummarySection.position)
    ).scalars().all()

    encounter_id = f"encounter-{visit.id}"
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

    entries: list[dict[str, Any]] = [
        {
            "resource": {
                "resourceType": "Encounter",
                "id": encounter_id,
                "status": "finished",
                "class": {"code": "AMB"},
                "subject": {"reference": f"Patient/{patient.hospital_mrn}"},
            }
        },
        {
            "resource": {
                "resourceType": "Composition",
                "id": f"composition-{visit.id}",
                "status": "final",
                "type": {"coding": [{"system": "http://loinc.org", "code": "11488-4", "display": "Consult note"}]},
                "title": "Medify SOAP Summary",
                "date": dt.datetime.now(dt.timezone.utc).isoformat(),
                "section": composition_sections,
            }
        },
    ]
    entries += [{"resource": resource} for resource in conditions + medication_requests + procedures]

    return {
        "resourceType": "Bundle",
        "id": f"medify-visit-{visit.id}",
        "type": "transaction",
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "entry": entries,
    }


def store_bundle(visit_id: uuid.UUID, bundle: dict[str, Any]) -> str:
    """يُخزَّن مرجع الحزمة (fhir_payload_ref) — يُبنى وقت الاعتماد داخل سياق الدكتور (D-19)."""
    base = Path(get_settings().recordings_dir).parent / "fhir"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{visit_id}.json"
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(path)
