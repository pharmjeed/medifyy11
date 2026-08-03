"""سحب سياق المريض من نظام المستشفى (م17) — خلف feature flag، غير معطِّل.

القراءة async غير معطِّلة عند إنشاء الزيارة: Patient · Condition(active) ·
MedicationRequest(active) · AllergyIntolerance من FHIR endpoint للـHIS.
timeout (افتراضي 5ث) أو أي فشل → الزيارة تمضي مع context_unavailable=true.

العلم مطفأ افتراضياً (HIS_CONTEXT_ENABLED=false). لا PHI في أي log — الأخطاء
تُسجَّل بالنوع والحالة فقط، والمحتوى يذهب مباشرة إلى اللقطة المشفّرة.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import IntegrationConfig, Patient

logger = logging.getLogger("medify.his_context")

RESOURCES = ("Condition", "MedicationRequest", "AllergyIntolerance")


def his_context_enabled() -> bool:
    return get_settings().his_context_enabled


def _endpoint_base(db: Session, facility_id) -> str | None:
    config = db.execute(
        select(IntegrationConfig).where(IntegrationConfig.facility_id == facility_id)
    ).scalar_one_or_none()
    if config is None or not config.endpoint_url:
        return None
    if not config.endpoint_url.startswith(("http://", "https://")):
        return None  # وجهة MLLP لا تصلح للقراءة
    return config.endpoint_url.rstrip("/")


def _texts(bundle: dict[str, Any], picker) -> list[str]:
    out: list[str] = []
    for entry in (bundle.get("entry") or []):
        resource = entry.get("resource") or {}
        value = picker(resource)
        if value:
            out.append(str(value))
    return out


def _concept_text(concept: dict[str, Any] | None) -> str | None:
    if not isinstance(concept, dict):
        return None
    if concept.get("text"):
        return concept["text"]
    for coding in (concept.get("coding") or []):
        if coding.get("display"):
            return coding["display"]
        if coding.get("code"):
            return coding["code"]
    return None


def fetch_his_context(db: Session, patient: Patient, facility_id) -> dict[str, Any]:
    """يعيد لقطة سياق HIS — أو {available: False} عند أي تعذّر (لا يرفع أبداً)."""
    if not his_context_enabled():
        return {"source": "his_fhir", "available": False, "reason": "disabled"}
    base = _endpoint_base(db, facility_id)
    if base is None:
        return {"source": "his_fhir", "available": False, "reason": "no_endpoint"}

    settings = get_settings()
    mrn = patient.hospital_mrn
    result: dict[str, Any] = {
        "source": "his_fhir",
        "available": False,
        "problems": [],
        "medications": [],
        "allergies": [],
        "demographics": {},
    }
    try:
        with httpx.Client(timeout=settings.his_context_timeout_seconds) as client:
            patient_response = client.get(f"{base}/Patient", params={"identifier": mrn})
            patient_response.raise_for_status()
            patient_bundle = patient_response.json()
            entries = patient_bundle.get("entry") or []
            if not entries:
                return {**result, "reason": "patient_not_found"}
            patient_resource = entries[0].get("resource") or {}
            patient_ref = patient_resource.get("id") or mrn
            result["demographics"] = {
                "gender": patient_resource.get("gender"),
                "birth_date": patient_resource.get("birthDate"),
            }

            for resource_type in RESOURCES:
                params: dict[str, str] = {"patient": str(patient_ref)}
                if resource_type == "Condition":
                    params["clinical-status"] = "active"
                elif resource_type == "MedicationRequest":
                    params["status"] = "active"
                response = client.get(f"{base}/{resource_type}", params=params)
                response.raise_for_status()
                bundle = response.json()
                if resource_type == "Condition":
                    result["problems"] = _texts(bundle, lambda r: _concept_text(r.get("code")))
                elif resource_type == "MedicationRequest":
                    result["medications"] = _texts(
                        bundle, lambda r: _concept_text(r.get("medicationCodeableConcept")))
                else:
                    result["allergies"] = _texts(bundle, lambda r: _concept_text(r.get("code")))
        result["available"] = True
        return result
    except httpx.TimeoutException:
        logger.warning("انتهت مهلة سياق HIS (%.1fs) — الزيارة تمضي بلا سياق",
                       settings.his_context_timeout_seconds)
        return {**result, "reason": "timeout"}
    except Exception as exc:  # لا PHI في السجل — النوع فقط
        logger.warning("تعذّر سياق HIS (%s) — الزيارة تمضي بلا سياق", exc.__class__.__name__)
        return {**result, "reason": "error"}


def merge_context(medify_context: dict[str, Any], his: dict[str, Any]) -> dict[str, Any]:
    """دمج سياق ميديفاي (المراجعات السابقة) مع سياق HIS — بلا تكرار، ومصدر كل بند واضح."""
    merged = dict(medify_context)
    merged["context_unavailable"] = not his.get("available", False)
    merged["his"] = {
        "available": his.get("available", False),
        "reason": his.get("reason"),
        "problems": his.get("problems", []),
        "medications": his.get("medications", []),
        "allergies": his.get("allergies", []),
        "demographics": his.get("demographics", {}),
    }
    if his.get("available"):
        for problem in his.get("problems", []):
            if problem not in merged.get("problems", []):
                merged.setdefault("problems", []).append(problem)
        for medication in his.get("medications", []):
            if medication not in merged.get("medications", []):
                merged.setdefault("medications", []).append(medication)
        merged["allergies"] = list(his.get("allergies", []))
    return merged
