"""نص موافقة المريض الموثّقة — ثنائي اللغة ومُصدَّر (توجيه المالك 2026-07-22، A1).

النص مصدر حقيقة واحد: يُعرض للطبيب كما هو، وتُخزَّن بصمته مع الموافقة ليثبت لاحقاً
أيّ نص بالضبط أُقرَّ به. تغيير النص يستلزم رفع الإصدار في `settings.consent_version`.
"""
from __future__ import annotations

import hashlib

from ..config import get_settings

CONSENT_TEXT_AR = (
    "سيقوم الطبيب باستخدام مساعد توثيق طبي يسجّل صوت هذه الاستشارة لتحويلها إلى "
    "مذكرة طبية تُضاف إلى ملفك في نظام المنشأة. لا يُستخدم التسجيل لأي غرض آخر، "
    "ويُحذف الصوت آلياً بانتهاء مدة الاحتفاظ المعتمدة. لك أن ترفض التسجيل دون أن "
    "يؤثر ذلك على تقديم الرعاية لك، ولك أن تطلب إيقافه في أي لحظة أثناء الاستشارة. "
    "لا تخرج أي بيانات من النظام قبل مراجعة الطبيب واعتماده لها."
)

CONSENT_TEXT_EN = (
    "Your doctor will use a medical documentation assistant that records the audio of this "
    "consultation to produce a clinical note added to your file in the facility system. The "
    "recording is not used for any other purpose and the audio is deleted automatically at the "
    "end of the approved retention period. You may decline recording without affecting your care, "
    "and you may ask to stop it at any moment during the consultation. No data leaves the system "
    "before your doctor reviews and approves it."
)

ACK_TEXT_AR = "أقرّ بأنني شرحت النص أعلاه للمريض وأنه وافق على التسجيل."
ACK_TEXT_EN = "I confirm I explained the text above to the patient and that they consented to recording."


def consent_text_hash(version: str = "") -> str:
    """بصمة النص المعروض بالضبط — تُخزَّن مع الموافقة (إثبات ما أُقرَّ به)."""
    version = version or get_settings().consent_version
    payload = "\n".join([version, CONSENT_TEXT_AR, CONSENT_TEXT_EN, ACK_TEXT_AR, ACK_TEXT_EN])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def consent_document() -> dict[str, str]:
    """الوثيقة التي تعرضها الواجهة قبل أي تسجيل."""
    version = get_settings().consent_version
    return {
        "version": version,
        "text_ar": CONSENT_TEXT_AR,
        "text_en": CONSENT_TEXT_EN,
        "ack_ar": ACK_TEXT_AR,
        "ack_en": ACK_TEXT_EN,
        "text_hash": consent_text_hash(version),
    }
