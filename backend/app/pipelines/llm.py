"""محرك LLM قابل للتبديل — LLM_ENGINE=claude|mock (CLAUDE-CODE-PROMPT §٥).

عند غياب ANTHROPIC_API_KEY يعمل mock بمخرجات JSON صالحة سريرياً — البناء لا يتوقف (D-03).
كل استدعاء يسجّل {pipeline_id, prompt_version, model_ref} — DOC-08 §٦ / DOC-14.
"""
from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..config import get_settings

logger = logging.getLogger("medify.pipelines")

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def load_prompt(prompt_id: str, version: str = "1.0") -> str:
    return (PROMPTS_DIR / f"{prompt_id}@{version}.txt").read_text(encoding="utf-8")


def render_prompt(template: str, variables: dict[str, Any]) -> str:
    rendered = template
    for key, value in variables.items():
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, indent=1)
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


class LLMEngine(ABC):
    @abstractmethod
    def complete_json(
        self,
        prompt_id: str,
        version: str,
        variables: dict[str, Any],
        attachments: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], str]:
        """تعيد (المخرج JSON، model_ref). المرفقات (صورة/PDF) قابلة للقراءة متعدد الوسائط.

        ترفع ValueError إن تعذّر مخرج صالح بعد إعادة محاولة واحدة.
        """


def _content_blocks(rendered: str, attachments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """يبني كتل محتوى Anthropic: مرفقات (صورة/PDF) ثم نص المطالبة."""
    blocks: list[dict[str, Any]] = []
    for attachment in attachments or []:
        media_type = attachment["media_type"]
        source = {"type": "base64", "media_type": media_type, "data": attachment["data"]}
        block_type = "document" if media_type == "application/pdf" else "image"
        blocks.append({"type": block_type, "source": source})
    blocks.append({"type": "text", "text": rendered})
    return blocks


class ClaudeEngine(LLMEngine):
    def __init__(self) -> None:
        import anthropic

        s = get_settings()
        self._client = anthropic.Anthropic(api_key=s.anthropic_api_key)
        self._model = s.anthropic_model

    def _call(self, rendered: str, attachments: list[dict[str, Any]] | None) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            messages=[{"role": "user", "content": _content_blocks(rendered, attachments)}],
        )
        return "".join(block.text for block in response.content if block.type == "text")

    def complete_json(
        self,
        prompt_id: str,
        version: str,
        variables: dict[str, Any],
        attachments: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], str]:
        rendered = render_prompt(load_prompt(prompt_id, version), variables)
        model_ref = f"{prompt_id}@{version}/{self._model}"
        for attempt in range(2):  # مخرج غير مطابق → إعادة استدعاء واحدة (DOC-08 §٦)
            raw = self._call(rendered, attachments)
            try:
                return _extract_json(raw), model_ref
            except ValueError:
                if attempt == 1:
                    raise
                logger.warning("مخرج غير مطابق للعقد من %s — إعادة المحاولة", prompt_id)
        raise ValueError("unreachable")


def _extract_json(raw: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in model output")
    return json.loads(match.group(0))


class MockLLMEngine(LLMEngine):
    """عيّنات ثابتة معقولة سريرياً — تطابق عقود مخرجات DOC-15 (D-03)."""

    def complete_json(
        self,
        prompt_id: str,
        version: str,
        variables: dict[str, Any],
        attachments: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], str]:
        model_ref = f"{prompt_id}@{version}/mock"
        handler = {
            "P2-summary": self._summary,
            "P3-guidance": self._guidance,
            "P4-reverse-template": self._reverse,
            "P5-edit-chat": self._chat,
        }[prompt_id]
        return handler(variables), model_ref

    def _summary(self, variables: dict[str, Any]) -> dict[str, Any]:
        structure = variables.get("template_structure") or {}
        sections = structure.get("sections") if isinstance(structure, dict) else None
        if not sections:
            sections = [
                {"section_key": "S", "title": "Subjective"},
                {"section_key": "O", "title": "Objective"},
                {"section_key": "A", "title": "Assessment"},
                {"section_key": "P", "title": "Plan"},
            ]
        samples = {
            "S": "Patient reports intermittent frontal headache for 5 days, worse in the morning, "
                 "associated with mild dizziness. Reports poor medication adherence over the past month. "
                 "No visual aura, no vomiting.",
            "O": "BP 165/95 mmHg, HR 82 bpm regular, Temp 36.8°C. Alert and oriented. "
                 "Cardiac exam: normal S1/S2, no murmurs. Neurological exam grossly intact.",
            "A": "Uncontrolled hypertension, likely secondary to poor adherence. "
                 "Tension-type headache, most probably related to elevated blood pressure.",
            "P": "Resume amlodipine 5 mg once daily. Home BP monitoring twice daily for two weeks. "
                 "Follow-up in 2 weeks with BP log. Return immediately if severe headache or visual changes.",
            "E": "Educated the patient on the importance of daily medication adherence, "
                 "low-salt diet, and recognizing hypertensive emergency warning signs.",
        }
        out = []
        for section in sections:
            key = section.get("section_key", "S")
            out.append({"section_key": key, "content": samples.get(key, "[Not discussed]")})
        return {"sections": out}

    def _guidance(self, variables: dict[str, Any]) -> dict[str, Any]:
        """عيّنة P3 v1.1 — بنود خطة مهيكلة بكودها ومبررها ودرجة ثقتها.

        البند الثاني ثقته دون العتبة عمداً: يُظهر سلوك «لا تخمين» (خانة كود فارغة + طلب إدخال الطبيب).
        """
        systems = str(variables.get("active_coding_systems", "ICD10AM"))
        has_sfda = "SFDA" in systems
        items: list[dict[str, Any]] = [
            {
                "section_key": "A", "kind": "clinical_dx",
                "suggestion_text": "Consider documenting essential (primary) hypertension explicitly — "
                                   "patient has 2 prior elevated readings in file plus today's 165/95.",
                "code_system": "ICD10AM", "code_value": "I10",
                "code_secondary_system": None, "code_secondary_value": None,
                "code_registry_version": "ICD-10-AM 12th ed.", "code_effective_date": "2025-07-01",
                "confidence": 0.94, "linked_dx_code": None, "justification": None,
                "evidence_source": "patient_file",
                "evidence_ref": "Previous visits 2026-05-02 and 2026-06-10: BP 158/92, 161/94",
                "safety_flag": False,
            },
            {
                "section_key": "A", "kind": "coding_match",
                "suggestion_text": "Headache pattern is consistent with tension-type headache, but the "
                                   "documentation does not distinguish it from migraine without aura.",
                "code_system": "ICD10AM", "code_value": "G44.2",
                "code_secondary_system": None, "code_secondary_value": None,
                "code_registry_version": "ICD-10-AM 12th ed.", "code_effective_date": "2025-07-01",
                "confidence": 0.61, "linked_dx_code": None, "justification": None,
                "evidence_source": "current_visit",
                "evidence_ref": "Patient reports frontal headache 5 days, no aura documented",
                "safety_flag": False,
            },
            {
                "section_key": "P", "kind": "clinical_rx",
                "suggestion_text": "Verify amlodipine dose against the file history — prior ankle oedema on "
                                   "amlodipine 10 mg; current plan uses 5 mg.",
                "code_system": "SFDA" if has_sfda else "ICD10AM",
                "code_value": "SFDA-2100034521" if has_sfda else "I10",
                "code_secondary_system": "GTIN" if has_sfda else None,
                "code_secondary_value": "06285074001122" if has_sfda else None,
                "code_registry_version": "SFDA Drug List 2026-Q2", "code_effective_date": "2026-04-01",
                "confidence": 0.88, "linked_dx_code": "I10", "justification": None,
                "evidence_source": "patient_file",
                "evidence_ref": "Medication history: amlodipine 10 mg — ankle oedema 2025-11",
                "safety_flag": True,
            },
            {
                "section_key": "P", "kind": "clinical_service",
                "suggestion_text": "Fasting lipid profile is indicated for cardiovascular risk stratification "
                                   "in newly documented hypertension.",
                "code_system": "SBS", "code_value": "SBS-80061",
                "code_secondary_system": None, "code_secondary_value": None,
                "code_registry_version": "SBS 2026 release 1", "code_effective_date": "2026-01-01",
                "confidence": 0.91, "linked_dx_code": "I10", "justification": None,
                "evidence_source": "current_visit",
                "evidence_ref": "Clinician states: we will check cholesterol before next visit",
                "safety_flag": False,
            },
            {
                "section_key": "P", "kind": "clinical_device",
                "suggestion_text": "Dispense an ambulatory blood-pressure monitor for 7-day home readings.",
                "code_system": "GMDN", "code_value": "GMDN-35146",
                "code_secondary_system": "GTIN", "code_secondary_value": "04015630001231",
                "code_registry_version": "GMDN 2026-05", "code_effective_date": "2026-05-01",
                "confidence": 0.86, "linked_dx_code": "I10",
                "justification": "White-coat effect suspected: clinic readings elevated across three visits "
                                 "while the patient reports normal home readings — home monitoring is "
                                 "required before escalating therapy.",
                "evidence_source": "current_visit",
                "evidence_ref": "Clinician asks the patient to measure at home twice daily for a week",
                "safety_flag": False,
            },
        ]
        return {"items": items}

    def _reverse(self, variables: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": "قالب متابعة الأمراض المزمنة",
            "sections": [
                {"section_key": "S", "title": "Subjective", "instructions": "Summarize the patient's complaints in their own words, adherence, and symptom timeline."},
                {"section_key": "O", "title": "Objective", "instructions": "Record vital signs and focused physical examination findings mentioned by the clinician."},
                {"section_key": "A", "title": "Assessment", "instructions": "State the clinician's stated assessment only; do not infer new diagnoses."},
                {"section_key": "P", "title": "Plan", "instructions": "List medications, monitoring instructions, and follow-up interval as stated."},
                {"section_key": "E", "title": "Patient Education", "instructions": "Document education points and safety-net advice given to the patient."},
            ],
        }

    def _chat(self, variables: dict[str, Any]) -> dict[str, Any]:
        message = str(variables.get("message", ""))
        sections = variables.get("summary_sections_current") or []
        if len(message.strip()) < 6:
            return {"reply": "هل يمكن توضيح المطلوب تعديله تحديداً وفي أي قسم؟", "patches": []}
        target = None
        for section in sections:
            if isinstance(section, dict) and section.get("section_key") == "P":
                target = section
                break
        if target is None and sections and isinstance(sections[0], dict):
            target = sections[0]
        if target is None:
            return {"reply": "لا توجد أقسام قابلة للتعديل في هذا الملخص.", "patches": []}
        new_content = str(target.get("content", "")).rstrip()
        addition = " Follow-up appointment scheduled in 2 weeks; sooner if symptoms worsen."
        return {
            "reply": "تم تنفيذ طلبك وتحديث القسم المعني — راجع بطاقة الفرق أدناه.",
            "patches": [{"section_key": target.get("section_key", "P"), "new_content": new_content + addition}],
        }


_engine_instance: LLMEngine | None = None


def get_llm() -> LLMEngine:
    global _engine_instance
    if _engine_instance is None:
        s = get_settings()
        if s.llm_engine == "claude" and s.anthropic_api_key:
            _engine_instance = ClaudeEngine()
        else:
            if s.llm_engine == "claude":
                logger.warning("LLM_ENGINE=claude لكن ANTHROPIC_API_KEY غائب — تفعيل mock (D-03)")
            _engine_instance = MockLLMEngine()
    return _engine_instance


def reset_llm_cache() -> None:
    global _engine_instance
    _engine_instance = None
