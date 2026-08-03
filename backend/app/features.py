"""كتالوج مميزات الباقة — قرار مالك 2026-08-03 (يعدّل «لا باقات ميزات» في DOC-20 تعديل ٢).

الاشتراك يبقى **بعدد الدكاترة × تكلفة الدكتور**؛ ما يُضاف هنا هو أن كل باقة (`plans`) تحمل
كذلك **ما تُظهره للدكتور**: مالك المنصة يرتّب المميزات ويضمّها للباقة من `/sa/plans`.

الكتالوج في الكود لا في القاعدة عمداً: كل مفتاح مربوط بمسار تنفيذ فعلي (نقطة API + عنصر واجهة)،
فاختراع مفتاح من القاعدة يعني مفتاحاً بلا إنفاذ. القاعدة تحفظ **الاختيار** فقط (`plans.features`).

قواعد ملزمة:
- `core=True` = عمود المنتج (تسجيل/مذكرة/بوابتان/نقل) — لا يُطفأ أبداً، ويُعرض للعلم فقط.
- `default` = القيمة حين لا تحدد الباقة شيئاً — كلها True كي لا تفقد أي منشأة قائمة شيئاً بالترقية.
- الإنفاذ في الخادم (`services/features.require_feature`) لا في الواجهة؛ الإخفاء في الواجهة
  تجربة استخدام فقط، تماماً كحارس الدور في `Shell`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureDef:
    """ميزة واحدة قابلة للضم لباقة — الترتيب هو ترتيب ورودها في `FEATURE_CATALOG`."""

    key: str
    group: str
    name_ar: str
    name_en: str
    desc_ar: str
    desc_en: str
    default: bool = True
    core: bool = False


# مجموعات العرض في كونسول المالك — بالترتيب
FEATURE_GROUPS: list[tuple[str, str, str]] = [
    ("essentials", "أساس المنتج", "Product core"),
    ("conversation", "المحادثة والسند", "Conversation & evidence"),
    ("ai_assist", "مساعدة الذكاء", "AI assistance"),
    ("outputs", "المخارج", "Outputs"),
    ("lifecycle", "دورة التوثيق", "Documentation lifecycle"),
    ("templates", "القوالب", "Templates"),
]


FEATURE_CATALOG: list[FeatureDef] = [
    # ═══ أساس المنتج — لا يُطفأ (يظهر ليكتمل جدول «ماذا تشمل الباقة») ═══
    FeatureDef(
        key="visit.recording", group="essentials", core=True,
        name_ar="تسجيل الزيارة والتفريغ الآلي",
        name_en="Visit recording & transcription",
        desc_ar="التقاط المحادثة وتفريغها بعد الإنهاء — عمود المنتج.",
        desc_en="Capture the encounter and transcribe it after stop — the product core.",
    ),
    FeatureDef(
        key="visit.ai_note", group="essentials", core=True,
        name_ar="توليد المذكرة واقتراحات الترميز",
        name_en="Note generation & coding suggestions",
        desc_ar="مذكرة SOAP إنجليزية + اقتراحات أكواد محقّقة من السجل المرجعي.",
        desc_en="English SOAP note plus coding suggestions validated against the reference registry.",
    ),
    FeatureDef(
        key="visit.his_upload", group="essentials", core=True,
        name_ar="بوابتا الاعتماد والنقل لنظام المستشفى",
        name_en="Approval gates & hospital upload",
        desc_ar="اعتماد النص ثم الأكواد ثم النقل — لا خروج بيانات قبلهما.",
        desc_en="Note then codes approval then upload — no data leaves before both gates.",
    ),

    # ═══ المحادثة والسند — طلب المالك المباشر 2026-08-03 ═══
    FeatureDef(
        key="visit.transcript_view", group="conversation",
        name_ar="رؤية نص المحادثة الكامل",
        name_en="View the full transcript",
        desc_ar="زر «نص المحادثة الكامل» ولوح النص المُسند (W-220). بإطفائه يرى الدكتور المذكرة دون نص المحادثة.",
        desc_en="The “Full transcript” button and its evidence drawer (W-220). Off = the doctor sees the note without the raw conversation.",
    ),
    FeatureDef(
        key="visit.audio_playback", group="conversation",
        name_ar="سماع صوت الزيارة",
        name_en="Play back the visit audio",
        desc_ar="مشغّل السند 🎧 على كل فقرة والقفز للمقطع المصدر. الصوت يبقى محفوظاً ويخضع لسياسة الاحتفاظ في الحالتين.",
        desc_en="The 🎧 evidence player on each section and jumping to the source segment. Audio is still stored and retained either way.",
    ),

    # ═══ مساعدة الذكاء ═══
    FeatureDef(
        key="visit.ai_chat", group="ai_assist",
        name_ar="محادثة تعديل المذكرة بالذكاء",
        name_en="AI note-editing chat",
        desc_ar="طلب تعديل بالعربية يُطبَّق فروقاً على الأقسام (FR-707).",
        desc_en="Ask for an edit in Arabic and get patches applied to the sections (FR-707).",
    ),
    FeatureDef(
        key="visit.dictate", group="ai_assist",
        name_ar="الإملاء الصوتي على الفقرات",
        name_en="Voice dictation into sections",
        desc_ar="إملاء قصير يُدمج في الفقرة بدل الكتابة (FR-706).",
        desc_en="Short dictation merged into a section instead of typing (FR-706).",
    ),
    FeatureDef(
        key="visit.claim_readiness", group="ai_assist",
        name_ar="فاحص جاهزية المطالبة",
        name_en="Claim readiness checker",
        desc_ar="قواعد MDS/الربط قبل البوابة ②. بإطفائه لا يُفحص ولا يحجب الاعتماد (MDF-4237 لا يُطلق).",
        desc_en="MDS/linkage rules before gate ②. Off = no check and no approval block (MDF-4237 never fires).",
    ),

    # ═══ المخارج ═══
    FeatureDef(
        key="visit.export_pdf", group="outputs",
        name_ar="تصدير PDF بترويسة المنشأة",
        name_en="PDF export with facility letterhead",
        desc_ar="مخرج يوم-واحد قبل اكتمال التكامل — بعد البوابة ② حصراً.",
        desc_en="Day-one output before full integration — after gate ② only.",
    ),
    FeatureDef(
        key="visit.export_text", group="outputs",
        name_ar="نسخ نصي نظيف للـ EMR",
        name_en="Clean text copy for the EMR",
        desc_ar="نص جاهز للّصق في نظام المستشفى — بعد البوابة ② حصراً.",
        desc_en="Paste-ready text for the hospital system — after gate ② only.",
    ),
    FeatureDef(
        key="visit.patient_summary", group="outputs",
        name_ar="ملخص المريض بالعربية",
        name_en="Arabic patient summary",
        desc_ar="ملخص مبسّط للمريض بلغته + PDF مستقل — بعد البوابة ①.",
        desc_en="A plain-language summary for the patient plus its own PDF — after gate ①.",
    ),

    # ═══ دورة التوثيق ═══
    FeatureDef(
        key="visit.note_unlock", group="lifecycle",
        name_ar="فتح المذكرة (حلقة CDI)",
        name_en="Note unlock (CDI loop)",
        desc_ar="نقض البوابة ① بسبب مسجّل للتعديل قبل ② — بإطفائه يبقى النص مجمّداً بعد ①.",
        desc_en="Revoke gate ① with a recorded reason to edit before ② — off = the note stays frozen after ①.",
    ),
    FeatureDef(
        key="visit.addendum", group="lifecycle",
        name_ar="الملاحق بعد الاعتماد النهائي",
        name_en="Addendums after final approval",
        desc_ar="إضافة ملحق على مذكرة معتمدة ببوابة ① مصغّرة.",
        desc_en="Append an addendum to an approved note through a mini gate ①.",
    ),
    FeatureDef(
        key="visit.reopen", group="lifecycle",
        name_ar="إعادة الفتح ونسخة جديدة",
        name_en="Reopen into a new version",
        desc_ar="تعديل بعد النقل → نسخة جديدة → إعادة البوابتين → نقل بدلالة replace.",
        desc_en="Edit after upload → new version → both gates again → replace-flagged upload.",
    ),
    FeatureDef(
        key="visit.void", group="lifecycle",
        name_ar="إبطال الزيارة (Void)",
        name_en="Void a visit",
        desc_ar="إبطال سريري بسبب من قائمة — المحتوى يبقى للقراءة وتخرج الزيارة من المخارج.",
        desc_en="Clinical void with a listed reason — content stays readable and the visit leaves all outputs.",
    ),

    # ═══ القوالب ═══
    FeatureDef(
        key="templates.custom", group="templates",
        name_ar="قوالب تلخيص خاصة بالدكتور",
        name_en="Doctor-authored templates",
        desc_ar="إنشاء وتعديل وحذف القوالب. بإطفائه تبقى القوالب الجاهزة والمعيّنة من الأدمن فقط.",
        desc_en="Create, edit and delete templates. Off = only the ready-made and admin-assigned templates remain.",
    ),
    FeatureDef(
        key="templates.reverse_build", group="templates",
        name_ar="بناء قالب من نموذج موجود",
        name_en="Reverse-build a template",
        desc_ar="استخراج بنية قالب من مذكرة نموذجية يلصقها الدكتور.",
        desc_en="Derive a template structure from a sample note the doctor pastes.",
    ),
]

FEATURE_BY_KEY: dict[str, FeatureDef] = {f.key: f for f in FEATURE_CATALOG}
CORE_KEYS: frozenset[str] = frozenset(f.key for f in FEATURE_CATALOG if f.core)

assert len(FEATURE_BY_KEY) == len(FEATURE_CATALOG), "مفتاح ميزة مكرر في الكتالوج"
assert all(f.group in {g[0] for g in FEATURE_GROUPS} for f in FEATURE_CATALOG), "مجموعة غير معرّفة"


def catalog_out() -> list[dict[str, object]]:
    """الكتالوج بصيغة العرض — يستهلكه كونسول المالك وواجهة المنشأة معاً."""
    labels = {code: (ar, en) for code, ar, en in FEATURE_GROUPS}
    return [
        {
            "key": f.key,
            "group": f.group,
            "group_name_ar": labels[f.group][0],
            "group_name_en": labels[f.group][1],
            "name_ar": f.name_ar,
            "name_en": f.name_en,
            "desc_ar": f.desc_ar,
            "desc_en": f.desc_en,
            "default": f.default,
            "core": f.core,
        }
        for f in FEATURE_CATALOG
    ]
