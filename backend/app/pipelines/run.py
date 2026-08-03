"""تشغيل خطوط المعالجة P1..P5 على الزيارة — كلها عبر طبقة الخدمة (DOC-08 المعدّل بقرار مالك 2026-08-02)."""
from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analytics import track
from ..config import get_settings
from ..errors import MedifyError
from ..models import (
    AudioChunk,
    CodingSystemConfig,
    GuidanceItem,
    Patient,
    PatientContextSnapshot,
    PlatformDefaultPrompt,
    Recording,
    Summary,
    SummarySection,
    Template,
    Transcript,
    Visit,
)
from ..notify import notify
from ..services.code_registry import check_code, registry_systems
from ..services.evidence import build_section_evidence, refresh_section_evidence
from ..services.history import previous_visits
from .deidentify import build_map
from .llm import get_llm
from .speaker import attribute_segments
from .streaming import IncrementalTranscript, stream_from_ledger

logger = logging.getLogger("medify.pipelines")

PROMPT_VERSIONS = {
    "P2-summary": "1.0",
    # تمريرة السند (قرار مالك 2026-08-02): كل جملة بلا سند تُحذف قبل أن يراها الدكتور.
    # 1.1 (م10): الربط جملةً بمقاطعها يُعاد ويُحفظ (evidence_json) بدل أن يُرمى.
    "P2-verify": "1.1",
    # 1.2: المراجعات السابقة مدخل صريح + إرشاد تشخيصي/علاجي عملي (تعديل مالك 2026-07-26)
    "P3-guidance": "1.2",
    "P4-reverse-template": "1.0",
    "P5-edit-chat": "1.0",
}


def _transcript_text(transcript: Transcript) -> str:
    """نص المحادثة مُسنَداً للمتحدث (الطبيب/المريض:) ليُميّز الملخص من قال ماذا."""
    segments = (transcript.content_json or {}).get("segments", [])
    lines: list[str] = []
    for segment in segments:
        text = segment.get("text", "")
        if not text:
            continue
        speaker = segment.get("speaker")
        prefix = {"doctor": "الطبيب: ", "patient": "المريض: "}.get(speaker, "")
        lines.append(f"{prefix}{text}")
    return "\n".join(lines)


def _active_coding_systems(db: Session, facility_id: uuid.UUID) -> list[str]:
    rows = db.execute(
        select(CodingSystemConfig).where(
            CodingSystemConfig.facility_id == facility_id,
            CodingSystemConfig.is_active == True,  # noqa: E712
        )
    ).scalars().all()
    return [row.system for row in rows] or ["ICD10AM"]


def _load_prompt_content(db: Session, template: Template) -> str:
    """تحميل محتوى البرومبت من Database:
    1. إن كان للقالب prompt_content مخصص (custom) → استخدمه
    2. وإلا استخدم البرومبت الافتراضي من SuperAdmin
    (FR-500+)
    """
    # إن كان البرومبت مخصصاً، استخدمه
    if template.prompt_source == "custom" and template.prompt_content:
        return template.prompt_content

    # استخدم البرومبت الافتراضي من SuperAdmin
    if template.prompt_template_type:
        default_prompt = db.execute(
            select(PlatformDefaultPrompt).where(
                PlatformDefaultPrompt.template_type == template.prompt_template_type,
                PlatformDefaultPrompt.is_active == True,  # noqa: E712
            )
        ).scalar_one_or_none()
        if default_prompt:
            return default_prompt.prompt_content

    # fallback: من الملفات (للتوافقية العكسية مع البيانات القديمة)
    from .llm import load_prompt
    # استنتاج نوع البرومبت من اسم القالب
    if "كشف" in (template.name or "") or "أول" in (template.name or ""):
        prompt_type = "first_visit"
    elif "استشارة" in (template.name or ""):
        prompt_type = "consultation"
    else:
        prompt_type = "follow_up"
    try:
        version = PROMPT_VERSIONS.get("P2-summary", "1.0")
        return load_prompt("P2-summary", version)
    except Exception:
        # إن فشل التحميل، رجّع نص فارغ والخطأ سيظهر من المحرك
        return ""


def run_transcription(db: Session, visit: Visit) -> Transcript:
    """P1 — التفريغ الكامل بعد إنهاء المحادثة (قرار مالك 2026-08-02): الملف كله تمريرة واحدة.

    إسناد المتحدث من كامل المحادثة: المحرك المميِّز صوتياً (gemini) يعيده مع كل مقطع،
    وإلا يُسند لغوياً على كامل قائمة المقاطع. أخطاء عابرة → إعادة محاولة تلقائية بـ backoff
    (30 ثانية → دقيقتين → 5 دقائق). فشل نهائي → MDF-5031 يوقف التدفق — لا يُلخَّص كلام لم يُفرَّغ.
    """
    recording = db.execute(select(Recording).where(Recording.visit_id == visit.id)).scalar_one_or_none()
    audio_path = recording.storage_uri if recording is not None else ""
    # م18: التفريغ عبر واجهة التدفق — الوضع الحالي (batch) حالة خاصة منها: تغذية
    # مقاطع السجل (وحدة م2 نفسها) ثم finalize بنتيجة مطابقة حرفياً للمسار القديم.
    # الاستثناءات تُرفع خاماً — التصنيف والإعادة وتغليف MDF-5031 في services/processing (م3).
    chunks = db.execute(
        select(AudioChunk).where(AudioChunk.visit_id == visit.id).order_by(AudioChunk.chunk_index)
    ).scalars().all()
    segments = stream_from_ledger(
        audio_path,
        [{"chunk_index": chunk.chunk_index, "byte_length": chunk.byte_length} for chunk in chunks],
    )

    # المحرك الذي لا يميّز المتحدث صوتياً → إسناد لغوي على المحادثة كاملة (سياق تبادل الأدوار كله)
    if segments and not all(segment.get("speaker") in ("doctor", "patient") for segment in segments):
        attribute_segments(segments)

    # م18: التفريغ المتزايد بنقطة finalize — P2 يقرأ من هنا (يُستدعى مباشرةً اليوم)
    incremental = IncrementalTranscript()
    incremental.extend(segments)
    content = incremental.finalize()
    stats: dict[str, Any] = {"segments": len(segments)}
    # م11: إحصاء ثقة التفريغ (whisper يوفرها؛ gemini بلا ثقة ASR فتغيب الإحصاءات)
    confidences = [s["confidence"] for s in segments if isinstance(s.get("confidence"), (int, float))]
    if confidences:
        stats["confidence_mean"] = round(sum(confidences) / len(confidences), 3)
        stats["confidence_min"] = round(min(confidences), 3)
    transcript = db.execute(select(Transcript).where(Transcript.visit_id == visit.id)).scalar_one_or_none()
    if transcript is None:
        transcript = Transcript(
            visit_id=visit.id,
            facility_id=visit.facility_id,
            content_json=content,
            language_stats=stats,
        )
        db.add(transcript)
    else:
        transcript.content_json = content
        transcript.language_stats = stats
    db.flush()
    return transcript


def _verify_sections(transcript_scrubbed: str, sections_out: list[dict],
                     segments: list[dict]) -> tuple[list[dict], dict[str, list[dict]]]:
    """P2-verify@1.1 — حذف ما لا سند له + ربط كل جملة باقية بمقاطعها (م10).

    يعيد (الأقسام المنقّحة، خريطة section_key → sentences بالربط).
    الفشل لا يوقف التدفق: تمضي الأقسام غير المنقّحة بلا سند — البوابة ① فوق الجميع.
    """
    version = PROMPT_VERSIONS["P2-verify"]
    try:
        output, _model_ref = get_llm().complete_json(
            "P2-verify",
            version,
            {
                "transcript": transcript_scrubbed,
                "segments": [
                    {"id": s.get("id"), "t0": s.get("t0"), "t1": s.get("t1"), "text": s.get("text")}
                    for s in segments
                ],
                "sections": [
                    {"section_key": section.get("section_key"), "content": section.get("content")}
                    for section in sections_out
                ],
            },
        )
        verified = output["sections"]
        assert isinstance(verified, list) and verified
        by_key = {str(section.get("section_key")): section for section in verified}
        merged = [
            {**section,
             "content": str(by_key.get(str(section.get("section_key")), section).get("content",
                                                                                     section.get("content", "")))}
            for section in sections_out
        ]
        sentences_by_key = {
            key: (entry.get("sentences") or [])
            for key, entry in by_key.items()
        }
        return merged, sentences_by_key
    except Exception as exc:
        logger.warning("P2-verify تعذّرت (%s) — تمضي الأقسام غير المنقّحة لمراجعة الدكتور", exc)
        return sections_out, {}


def run_summary(db: Session, visit: Visit) -> Summary:
    """P2 — التلخيص بالقالب. فشل بعد إعادة المحاولة → MDF-5032 (إعادة المحاولة داخل المحرك)."""
    transcript = db.execute(select(Transcript).where(Transcript.visit_id == visit.id)).scalar_one()
    template = db.execute(select(Template).where(Template.id == visit.template_id)).scalar_one()
    patient = db.execute(select(Patient).where(Patient.id == visit.patient_id)).scalar_one()

    deid = build_map(patient.display_name, patient.hospital_mrn)
    transcript_scrubbed = deid.scrub(_transcript_text(transcript))
    version = PROMPT_VERSIONS["P2-summary"]

    # تحميل البرومبت من قاعدة البيانات (مخصص أو افتراضي أو من الملفات)
    custom_prompt = _load_prompt_content(db, template)

    # م17: سياق المريض (بما فيه HIS إن توفّر) يُحقن مع تعليمة «لا تخترع منه وقائع»
    context_snapshot = None
    if visit.context_snapshot_id:
        context_snapshot = db.execute(
            select(PatientContextSnapshot).where(PatientContextSnapshot.id == visit.context_snapshot_id)
        ).scalar_one_or_none()
    context_json = (context_snapshot.content_json if context_snapshot else {}) or {}

    # الاستثناءات خام — التصنيف/الإعادة وتغليف MDF-5032 في services/processing (المرحلة 3)
    output, model_ref = get_llm().complete_json(
        "P2-summary",
        version,
        {
            "transcript": transcript_scrubbed,
            "patient_context": deid.scrub(json.dumps(context_json, ensure_ascii=False)),
            "template_structure": template.structure_json,
            "specialty": template.specialty or "",
            "visit_type": template.visit_type or "",
            "custom_prompt": custom_prompt,
        },
    )
    sections_out = output["sections"]
    assert isinstance(sections_out, list) and sections_out

    # تمريرة السند قبل أن يرى الدكتور أي شيء — ما لا سند له يُحذف، والربط يُحفظ (م10)
    segments = (transcript.content_json or {}).get("segments", [])
    sections_out, sentences_by_key = _verify_sections(transcript_scrubbed, sections_out, segments)
    segments_by_id = {str(s.get("id")): s for s in segments if s.get("id")}

    summary = Summary(
        visit_id=visit.id,
        facility_id=visit.facility_id,
        model_ref=model_ref,
        generated_at=dt.datetime.now(dt.timezone.utc),
    )
    db.add(summary)
    db.flush()
    for index, section in enumerate(sections_out):
        content = deid.restore(str(section.get("content", "")))
        key = str(section.get("section_key", f"X{index}"))
        evidence = build_section_evidence(sentences_by_key.get(key, []), segments_by_id)
        for entry in evidence:
            entry["text"] = deid.restore(entry["text"])  # نص الجملة يعود لهويته قبل التخزين
        db.add(
            SummarySection(
                summary_id=summary.id,
                facility_id=visit.facility_id,
                section_key=key,
                position=index,
                content_current=content,
                content_original=content,
                evidence_json=evidence or None,
            )
        )
    db.flush()
    # م11: درجات الثقة تدخل telemetry كأرقام فقط
    confidence_props = {}
    if isinstance(transcript.language_stats, dict):
        for stat_key in ("confidence_mean", "confidence_min"):
            value = transcript.language_stats.get(stat_key)
            if isinstance(value, (int, float)):
                confidence_props[stat_key] = value
    track(
        "summary.generated", visit.facility_id, "doctor", visit.id,
        sections_count=len(sections_out), prompt_version=version, model_ref=model_ref,
        **confidence_props,
    )
    return summary


def run_guidance(db: Session, visit: Visit, summary: Summary) -> bool:
    """P3 — الإرشاد المدمج. الاستثناءات خام؛ عدم الحجب (ملخص بلا إرشادات + W-224/MDF-5033)
    تتولاه services/processing بعد استنفاد الإعادات (المرحلة 3)."""
    sections = db.execute(
        select(SummarySection).where(SummarySection.summary_id == summary.id).order_by(SummarySection.position)
    ).scalars().all()
    snapshot = None
    if visit.context_snapshot_id:
        snapshot = db.execute(
            select(PatientContextSnapshot).where(PatientContextSnapshot.id == visit.context_snapshot_id)
        ).scalar_one_or_none()
    transcript = db.execute(select(Transcript).where(Transcript.visit_id == visit.id)).scalar_one_or_none()
    patient = db.execute(select(Patient).where(Patient.id == visit.patient_id)).scalar_one()

    deid = build_map(patient.display_name, patient.hospital_mrn)
    systems = _active_coding_systems(db, visit.facility_id)
    version = PROMPT_VERSIONS["P3-guidance"]
    by_key = {section.section_key: section for section in sections}

    # المراجعات السابقة: من اللقطة إن حملتها (ما رآه الطبيب فعلاً عند بدء الزيارة)، وإلا تُبنى الآن
    context_json = (snapshot.content_json if snapshot else {}) or {}
    history = context_json.get("previous_visits")
    if history is None:
        history = previous_visits(db, visit.patient_id, visit.doctor_id, exclude_visit_id=visit.id)

    # الاستثناءات خام — الإعادة على العابر وإخطار MDF-5033 غير المعطِّل في services/processing
    output, _model_ref = get_llm().complete_json(
        "P3-guidance",
        version,
        {
            "summary_sections": [
                {"section_key": s.section_key, "content": deid.scrub(s.content_current)} for s in sections
            ],
            "patient_context": deid.scrub(str(context_json)),
            "previous_visits": deid.scrub(json.dumps(history, ensure_ascii=False)),
            "transcript_highlights": deid.scrub(_transcript_text(transcript)[:2000] if transcript else ""),
            "active_coding_systems": ", ".join(systems),
        },
    )
    items = output["items"]
    assert isinstance(items, list)

    counts_by_kind: dict[str, int] = {}
    per_section: dict[str, int] = {}
    safety_flags = 0
    # السجل المرجعي (قرار مالك 2026-08-02): سجلنا مصدر الحقيقة للكود لا ذاكرة النموذج
    systems_loaded = registry_systems(db)
    for item in items:
        key = str(item.get("section_key", ""))
        section = by_key.get(key)
        if section is None:
            continue  # لا إرشاد بلا فقرة (ترشيح DOC-08 §٣)
        if not item.get("evidence_source") or not item.get("evidence_ref"):
            continue  # لا اقتراح بلا تعليل — قاعدة حاكمة
        if per_section.get(key, 0) >= 3:
            continue  # حد أقصى 3 إرشادات لكل فقرة (DOC-15 §٣)
        per_section[key] = per_section.get(key, 0) + 1
        kind = str(item.get("kind", "coding_match"))
        counts_by_kind[kind] = counts_by_kind.get(kind, 0) + 1
        safety = bool(item.get("safety_flag"))
        safety_flags += 1 if safety else 0
        code_system = item.get("code_system")
        # التشخيص/المطابقة تُصاغ بالنظام التشخيصي النشط حصراً؛ أما بنود الخطة المهيكلة
        # (دواء SFDA/GTIN · إجراء ACHI/SBS · خدمة SBS · جهاز GMDN/GTIN) فأنظمتها مقررة
        # بتوجيه المالك ولا تُقسر على النظام التشخيصي.
        if kind in ("clinical_dx", "coding_match") and code_system is not None and code_system not in systems:
            code_system = systems[0]

        # «لا تخمين» (توجيه المالك 2026-07-22): دون العتبة يُحجب الكود ويُطلب إدخال الطبيب
        try:
            confidence = float(item["confidence"]) if item.get("confidence") is not None else None
        except (TypeError, ValueError):
            confidence = None
        threshold = get_settings().code_confidence_threshold
        has_code = bool(item.get("code_value"))
        requires_input = has_code and (confidence is None or confidence < threshold)

        justification = item.get("justification")
        if kind == "clinical_device" and not justification:
            continue  # الجهاز بلا مبرر مرفوض (CHECK القاعدة يرفضه أصلاً)

        # التحقق المرجعي: valid → الصيغة القانونية وإصدار السجل من عندنا ·
        # unknown → «لا تخمين»: الكود يسقط ويُطلب إدخال الطبيب ·
        # inactive → يبقى معروضاً ببديله (البوابة ② تمنعه) · unchecked → كما ورد.
        code_value = item.get("code_value")
        registry_version = item.get("code_registry_version")
        effective_date = item.get("code_effective_date")
        verdict, entry = check_code(db, code_system, code_value, systems_loaded)
        if verdict == "valid":
            code_value = entry.code
            registry_version = entry.registry_version
            effective_date = entry.effective_date.isoformat() if entry.effective_date else None
        elif verdict == "unknown":
            code_value = None
            registry_version = None
            effective_date = None
            requires_input = True
        elif verdict == "inactive":
            code_value = entry.code
            registry_version = entry.registry_version
            effective_date = entry.effective_date.isoformat() if entry.effective_date else None

        secondary_value = item.get("code_secondary_value")
        secondary_verdict, secondary_entry = check_code(
            db, item.get("code_secondary_system"), secondary_value, systems_loaded
        )
        if secondary_verdict == "valid":
            secondary_value = secondary_entry.code
        elif secondary_verdict == "unknown":
            secondary_value = None  # كود ثانوي مخترع لا يدخل السجل السريري

        db.add(
            GuidanceItem(
                section_id=section.id,
                facility_id=visit.facility_id,
                kind=kind,
                suggestion_text=deid.restore(str(item.get("suggestion_text", ""))),
                code_system=code_system,
                code_value=code_value,
                code_secondary_system=item.get("code_secondary_system") if secondary_value else None,
                code_secondary_value=secondary_value,
                code_registry_version=registry_version,
                code_effective_date=effective_date,
                confidence=confidence,
                requires_doctor_input=requires_input,
                linked_dx_code=item.get("linked_dx_code"),
                justification=justification,
                evidence_source=str(item.get("evidence_source")),
                evidence_ref={"ref": deid.restore(str(item.get("evidence_ref", ""))), "safety_flag": safety},
                status="pending",
            )
        )
    db.flush()
    if safety_flags:
        notify(db, visit.facility_id, visit.doctor_id, "dr.safety_flag", {"visit_id": str(visit.id), "count": safety_flags})
    track("guidance.shown", visit.facility_id, "doctor", visit.id, counts_by_kind=counts_by_kind, safety_flags=safety_flags)
    return True


def run_reverse_template(
    sample_text: str, specialty: str, attachment: dict[str, Any] | None = None
) -> dict[str, Any]:
    """P4 — البناء العكسي من نص أو من مرفق (صورة/PDF). الفشل → MDF-5034. لا يُحفظ تلقائياً (FR-502)."""
    sample_for_prompt = sample_text.strip()
    if not sample_for_prompt and attachment is not None:
        kind = "PDF" if attachment.get("media_type") == "application/pdf" else "صورة"
        sample_for_prompt = f"(مثال الملاحظة مُرفق ك{kind} بهذه الرسالة — استنتج البنية من تخطيط المرفق وعناوين أقسامه.)"
    try:
        output, _model_ref = get_llm().complete_json(
            "P4-reverse-template",
            PROMPT_VERSIONS["P4-reverse-template"],
            {"sample_text": sample_for_prompt, "specialty": specialty},
            attachments=[attachment] if attachment is not None else None,
        )
        assert output.get("sections"), "بنية ناقصة"
        return output
    except Exception as exc:
        raise MedifyError("MDF-5034") from exc


def run_edit_chat(
    db: Session, visit: Visit, message: str, history: list[dict[str, Any]]
) -> dict[str, Any]:
    """P5 — محادثة التعديل الختامية. الغموض = سؤال توضيحي بلا patch."""
    summary = db.execute(select(Summary).where(Summary.visit_id == visit.id)).scalar_one()
    sections = db.execute(
        select(SummarySection).where(SummarySection.summary_id == summary.id).order_by(SummarySection.position)
    ).scalars().all()
    try:
        output, _model_ref = get_llm().complete_json(
            "P5-edit-chat",
            PROMPT_VERSIONS["P5-edit-chat"],
            {
                "message": message,
                "summary_sections_current": [
                    {"section_key": s.section_key, "content": s.content_current} for s in sections
                ],
                "chat_history": history,
            },
        )
    except Exception as exc:
        raise MedifyError("MDF-5034") from exc

    applied: list[dict[str, Any]] = []
    by_key = {section.section_key: section for section in sections}
    for patch in output.get("patches", []):
        section = by_key.get(str(patch.get("section_key", "")))
        if section is None:
            continue
        new_content = str(patch.get("new_content", ""))
        if not new_content:
            continue
        old_content = section.content_current
        section.content_current = new_content
        refresh_section_evidence(section)  # م10: الجمل الجديدة/المعدَّلة تُوسم «تحرير طبيب»
        applied.append(
            {
                "section_id": str(section.id),
                "section_key": section.section_key,
                "old_content": old_content,
                "new_content": new_content,
            }
        )
    db.flush()
    return {"reply": str(output.get("reply", "")), "patches": applied}
