"""محرك جاهزية المطالبة (م12) — service مستقل، قواعده بيانات لا كود.

المدخل: أكواد الزيارة المعتمدة مبدئياً + سياق الزيارة (+ الدافع إن توفر).
المخرج: [{rule_id, severity: pass|warn|block, message_ar, related_codes}].

القواعد في backend/rules/*.yaml بأربعة أنواع declarative (medical_necessity ·
mds_completeness · code_composition · prior_auth) — الشرح والأمثلة في rules/README.md.
إضافة قاعدة = سطر YAML، بلا نشر منطق.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Clinic, GuidanceItem, Patient, Summary, SummarySection, User, Visit

logger = logging.getLogger("medify.claim_readiness")

def _resolve_rules_dir() -> Path:
    """مجلد القواعد — يعمل من شجرة المصدر ومن الحزمة المثبَّتة (عامل arq) معاً.

    الأولوية: متغيّر البيئة · جوار الحزمة (backend/rules) · مجلد العمل (/app/rules).
    """
    import os

    candidates = [
        Path(os.environ["MEDIFY_RULES_DIR"]) if os.environ.get("MEDIFY_RULES_DIR") else None,
        Path(__file__).resolve().parents[2] / "rules",
        Path.cwd() / "rules",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parents[2] / "rules"  # الافتراضي للرسائل


RULES_DIR = _resolve_rules_dir()

DIAGNOSIS_KINDS_DEFAULT = ("clinical_dx", "coding_match")


@dataclass
class Finding:
    rule_id: str
    severity: str  # pass | warn | block
    message_ar: str
    related_codes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message_ar": self.message_ar,
            "related_codes": self.related_codes,
        }


@lru_cache(maxsize=1)
def _load_rules_cached(signature: tuple) -> list[dict]:
    import yaml

    rules: list[dict] = []
    for path in sorted(_resolve_rules_dir().glob("*.yaml")):
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        except Exception as exc:  # ملف معطوب لا يُسقط البوابة — يُسجَّل ويُتجاوز
            logger.error("قاعدة YAML معطوبة %s: %s", path.name, exc)
            continue
        if isinstance(loaded, list):
            rules.extend(rule for rule in loaded if isinstance(rule, dict))
    return rules


def load_rules() -> list[dict]:
    """يُعاد التحميل تلقائياً عند تغيّر أي ملف (mtime/الحجم) — قاعدة جديدة بلا إعادة تشغيل."""
    rules_dir = _resolve_rules_dir()  # يُحلّ عند كل نداء — لا يتعلق بمجلد العمل وقت الاستيراد
    signature = tuple(
        (path.name, path.stat().st_mtime_ns, path.stat().st_size)
        for path in sorted(rules_dir.glob("*.yaml"))
    )
    return [rule for rule in _load_rules_cached(signature) if rule.get("enabled", True)]


def _code_of(item: GuidanceItem) -> str:
    return f"{item.code_system or '—'} {item.code_value or '—'}".strip()


def _norm(code: str | None) -> str:
    return (code or "").replace(".", "").replace("-", "").upper()


def collect_visit_context(db: Session, visit: Visit) -> dict[str, Any]:
    """حقول MDS من الزيارة — قيمة None/فارغة تعني «ناقص» للقاعدة."""
    patient = db.execute(select(Patient).where(Patient.id == visit.patient_id)).scalar_one_or_none()
    doctor = db.execute(select(User).where(User.id == visit.doctor_id)).scalar_one_or_none()
    clinic = db.execute(select(Clinic).where(Clinic.id == visit.clinic_id)).scalar_one_or_none()
    summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one_or_none()
    return {
        "patient_mrn": patient.hospital_mrn if patient else None,
        "patient_dob": patient.dob if patient else None,
        "patient_gender": patient.gender if patient else None,
        "encounter_date": summary.generated_at.isoformat() if summary else None,
        "clinic": clinic.name if clinic else None,
        "physician_name": doctor.full_name if doctor else None,
        "payer": None,  # يُملأ عند وصول تكامل الدافع (م17/التكامل)
    }


def resolved_codes(db: Session, visit: Visit) -> list[GuidanceItem]:
    summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one_or_none()
    if summary is None:
        return []
    return list(db.execute(
        select(GuidanceItem)
        .join(SummarySection, SummarySection.id == GuidanceItem.section_id)
        .where(
            SummarySection.summary_id == summary.id,
            GuidanceItem.status.in_(["accepted", "modified"]),
        )
        .order_by(GuidanceItem.id)
    ).scalars().all())


# ===== مقيّمو الأنواع الأربعة =====

def _eval_medical_necessity(rule: dict, items: list[GuidanceItem], context: dict) -> list[Finding]:
    params = rule.get("params") or {}
    target_kinds = set(params.get("requires_link_for_kinds") or ())
    diagnosis_kinds = set(params.get("diagnosis_kinds") or DIAGNOSIS_KINDS_DEFAULT)
    diagnosis_system = params.get("diagnosis_system") or "ICD10AM"

    available_dx = {
        _norm(item.code_value) for item in items
        if item.kind in diagnosis_kinds and item.code_value
        and (item.code_system or diagnosis_system) == diagnosis_system
    }
    unlinked: list[str] = []
    for item in items:
        if item.kind not in target_kinds:
            continue
        linked = _norm(item.linked_dx_code)
        if not linked or linked not in available_dx:
            unlinked.append(_code_of(item))
    if unlinked:
        return [Finding(rule["rule_id"], rule.get("severity", "block"),
                        rule.get("message_ar", ""), unlinked)]
    return [Finding(rule["rule_id"], "pass", "كل البنود مرتبطة بتشخيص مبرِّر.", [])]


def _eval_mds(rule: dict, items: list[GuidanceItem], context: dict) -> list[Finding]:
    params = rule.get("params") or {}
    diagnosis_kinds = set(DIAGNOSIS_KINDS_DEFAULT)
    has_primary_dx = any(item.kind in diagnosis_kinds and item.code_value for item in items)
    findings: list[Finding] = []
    for spec in params.get("required_fields") or []:
        field_name = spec.get("field")
        if field_name == "primary_diagnosis":
            missing = not has_primary_dx
        else:
            value = context.get(field_name)
            missing = value is None or (isinstance(value, str) and not value.strip())
        if missing:
            findings.append(Finding(
                rule["rule_id"], rule.get("severity", "block"),
                spec.get("message_ar") or rule.get("message_ar", ""),
                [str(field_name)],
            ))
    if not findings:
        findings.append(Finding(rule["rule_id"], "pass", "بيانات المطالبة الإلزامية مكتملة.", []))
    return findings


def _eval_composition(rule: dict, items: list[GuidanceItem], context: dict) -> list[Finding]:
    params = rule.get("params") or {}
    severity = rule.get("severity", "block")
    present = {_norm(item.code_value): item for item in items if item.code_value}
    findings: list[Finding] = []

    # لا يصلح تشخيصاً أولياً — يسري عندما لا يوجد تشخيص آخر يحمل المطالبة
    banned = [_norm(code) for code in (params.get("not_primary_diagnosis") or [])]
    if banned:
        diagnoses = [item for item in items if item.kind in DIAGNOSIS_KINDS_DEFAULT and item.code_value]
        offending = [item for item in diagnoses if _norm(item.code_value) in banned]
        acceptable = [item for item in diagnoses if _norm(item.code_value) not in banned]
        if offending and not acceptable:
            findings.append(Finding(rule["rule_id"], severity, rule.get("message_ar", ""),
                                    [_code_of(item) for item in offending]))

    # كود مظهري يتطلب الحالة الأساسية
    for spec in params.get("manifestation_requires") or []:
        code_key = _norm(spec.get("code"))
        if code_key not in present:
            continue
        required = [_norm(code) for code in (spec.get("requires_any") or [])]
        if any(any(key.startswith(req) for key in present) for req in required):
            continue
        findings.append(Finding(
            rule["rule_id"], severity,
            spec.get("message_ar") or rule.get("message_ar", ""),
            [_code_of(present[code_key])],
        ))

    # أزواج متعارضة
    for spec in params.get("conflicting_pairs") or []:
        pair = [_norm(code) for code in (spec.get("pair") or [])]
        if len(pair) == 2 and all(code in present for code in pair):
            findings.append(Finding(
                rule["rule_id"], severity,
                spec.get("message_ar") or rule.get("message_ar", ""),
                [_code_of(present[pair[0]]), _code_of(present[pair[1]])],
            ))

    if not findings:
        findings.append(Finding(rule["rule_id"], "pass", "تركيب الأكواد سليم.", []))
    return findings


def _eval_prior_auth(rule: dict, items: list[GuidanceItem], context: dict) -> list[Finding]:
    params = rule.get("params") or {}
    exact = {_norm(code) for code in (params.get("codes") or [])}
    prefixes = tuple(_norm(prefix) for prefix in (params.get("code_prefixes") or []))
    flagged = [
        _code_of(item) for item in items
        if item.code_value and (
            _norm(item.code_value) in exact
            or (prefixes and _norm(item.code_value).startswith(prefixes))
        )
    ]
    if flagged:
        return [Finding(rule["rule_id"], rule.get("severity", "warn"),
                        rule.get("message_ar", ""), flagged)]
    return [Finding(rule["rule_id"], "pass", "لا بنود تتطلب تفويضاً مسبقاً.", [])]


_EVALUATORS = {
    "medical_necessity": _eval_medical_necessity,
    "mds_completeness": _eval_mds,
    "code_composition": _eval_composition,
    "prior_auth": _eval_prior_auth,
}


def evaluate_visit(db: Session, visit: Visit) -> dict[str, Any]:
    """تقييم الزيارة الحالية — يُستدعى عند دخول البوابة ② وبعد كل تغيير أكواد."""
    items = resolved_codes(db, visit)
    context = collect_visit_context(db, visit)
    findings: list[Finding] = []
    for rule in load_rules():
        evaluator = _EVALUATORS.get(str(rule.get("type")))
        if evaluator is None or not rule.get("rule_id"):
            continue
        try:
            findings.extend(evaluator(rule, items, context))
        except Exception as exc:  # قاعدة معطوبة لا تُسقط البوابة
            logger.error("قاعدة %s فشلت: %s", rule.get("rule_id"), exc)
    blocks = [f for f in findings if f.severity == "block"]
    return {
        "findings": [f.as_dict() for f in findings],
        "blocking_count": len(blocks),
        "warning_count": len([f for f in findings if f.severity == "warn"]),
        "ready": not blocks,
        "version": visit.cycle,
    }


def blocking_findings(db: Session, visit: Visit) -> list[dict[str, Any]]:
    result = evaluate_visit(db, visit)
    return [f for f in result["findings"] if f["severity"] == "block"]


def diagnosis_options(db: Session, visit: Visit) -> list[dict[str, Any]]:
    """تشخيصات الزيارة المعتمدة — تغذّي واجهة الربط في البوابة ② (اختيار افتراضي ذكي)."""
    return [
        {
            "item_id": str(item.id),
            "code_system": item.code_system,
            "code_value": item.code_value,
            "suggestion_text": item.suggestion_text,
        }
        for item in resolved_codes(db, visit)
        if item.kind in DIAGNOSIS_KINDS_DEFAULT and item.code_value
    ]


def unlinked_items(db: Session, visit: Visit) -> list[dict[str, Any]]:
    """البنود غير التشخيصية التي تنتظر ربطاً — واجهة الربط ترسمها مباشرة."""
    dx_codes = {_norm(option["code_value"]) for option in diagnosis_options(db, visit)}
    out: list[dict[str, Any]] = []
    for item in resolved_codes(db, visit):
        if item.kind in DIAGNOSIS_KINDS_DEFAULT:
            continue
        linked = _norm(item.linked_dx_code)
        if linked and linked in dx_codes:
            continue
        out.append({
            "item_id": str(item.id),
            "kind": item.kind,
            "code_system": item.code_system,
            "code_value": item.code_value,
            "suggestion_text": item.suggestion_text,
            "linked_dx_code": item.linked_dx_code,
        })
    return out
