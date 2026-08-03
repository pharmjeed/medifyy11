"use client";

/** الصفحة 15 — مساحة المراجعة الموحدة (المحورية):
 *  W-214 الأقسام + الإرشادات المضمّنة · W-215 تحرير كتابي · W-216 إملاء صوتي · W-217 محادثة AI ·
 *  W-218 بوابة الاعتماد · W-219 حالة الرفع · W-220 النص الكامل · W-222 تعارض ETag · W-224 فشل التحليل.
 *  الأقسام تُبنى ديناميكياً من بنية القالب — لا S/O/A/P مثبتة (قرار مالك 2026-07-14). */

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, apiWithHeaders, getToken } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import type {
  ChatPatch, CodeSearchResult, EvidenceSentence, GuidanceItem, SummarySection, TranscriptSegment,
  UploadStatus, VisitSummary,
} from "@/lib/types";
import { ProgressBar7 } from "@/components/ProgressBar7";
import { Shell } from "@/components/Shell";
import { Modal, SpeakerBadge, SpecBadge, SpecBar, useErrorScreen, useToast } from "@/components/ui";

const SECTION_TITLES: Record<string, { ar: string; en: string }> = {
  S: { ar: "الذاتي — Subjective", en: "Subjective" },
  O: { ar: "الموضوعي — Objective", en: "Objective" },
  A: { ar: "التقييم — Assessment", en: "Assessment" },
  P: { ar: "الخطة — Plan", en: "Plan" },
  E: { ar: "تثقيف المريض — Patient education", en: "Patient education" },
  H: { ar: "التاريخ المرضي — History", en: "History" },
};

const KIND_META: Record<GuidanceItem["kind"], { label: { ar: string; en: string }; bg: string; fg: string }> = {
  coding_match: { label: { ar: "ترميزي", en: "Coding" }, bg: "rgba(42,111,151,.12)", fg: "#3b82c4" },
  clinical_dx: { label: { ar: "سريري — تشخيص", en: "Clinical — diagnosis" }, bg: "#d6f5f2", fg: "#005a55" },
  clinical_rx: { label: { ar: "سريري — دواء", en: "Clinical — medication" }, bg: "#d6f5f2", fg: "#005a55" },
  clinical_procedure: { label: { ar: "سريري — إجراء", en: "Clinical — procedure" }, bg: "#d6f5f2", fg: "#005a55" },
  clinical_service: { label: { ar: "سريري — خدمة/مختبر", en: "Clinical — service/lab" }, bg: "#d6f5f2", fg: "#005a55" },
  clinical_device: { label: { ar: "سريري — جهاز", en: "Clinical — device" }, bg: "#d6f5f2", fg: "#005a55" },
};

const STATUS_META: Record<GuidanceItem["status"], { label: { ar: string; en: string }; bg: string; fg: string }> = {
  pending: { label: { ar: "معلق", en: "Pending" }, bg: "#fdf4e0", fg: "#9c6f00" },
  accepted: { label: { ar: "مقبول", en: "Accepted" }, bg: "#e6f7f4", fg: "#12a594" },
  rejected: { label: { ar: "مرفوض", en: "Rejected" }, bg: "#fbeaea", fg: "#d94b4b" },
  modified: { label: { ar: "مقبول — معدّل", en: "Accepted — modified" }, bg: "#e6f7f4", fg: "#12a594" },
};

const PENDING_TEXT = /\[[^\]]*\]/;

/* أسباب الإبطال (قرار مالك 2026-08-03) — القائمة نفسها في POST /visits/{id}/void */
const VOID_REASONS: { key: string; ar: string; en: string }[] = [
  { key: "wrong_patient", ar: "سُجّلت على ملف المريض الخطأ", en: "Recorded on the wrong patient file" },
  { key: "duplicate", ar: "زيارة مكررة أُنشئت بالغلط", en: "Duplicate visit created by mistake" },
  { key: "test_recording", ar: "تسجيل تجريبي / تدريب", en: "Test recording / training" },
  { key: "consent_withdrawn", ar: "المريض سحب موافقته", en: "Patient withdrew consent" },
  { key: "other", ar: "سبب آخر (يتطلب توضيحاً)", en: "Other (explanation required)" },
];

interface ChatMessage { who: "doctor" | "ai"; text: string; patches?: ChatPatch[]; undone?: boolean[] }

type UploadView = { phase: "idle" } | { phase: "uploading" } | { phase: "done"; status: UploadStatus };

function ExportButtons(props: {
  L: (ar: string, en: string) => string;
  onPdf: () => void;
  onCopy: () => void;
}) {
  const { L, onPdf, onCopy } = props;
  return (
    <span style={{ display: "inline-flex", gap: 8 }}>
      <button className="btn-secondary" onClick={onCopy} title={L("نسخ نصي نظيف للصقه في الـ EMR", "Clean text copy to paste into the EMR")}>
        {L("⧉ نسخ للـ EMR", "⧉ Copy for EMR")}
      </button>
      <button className="btn" onClick={onPdf} title={L("PDF بترويسة المنشأة ثنائية اللغة", "PDF with the bilingual facility letterhead")}>
        {L("⭳ PDF", "⭳ PDF")}
      </button>
    </span>
  );
}

export default function ReviewPage() {
  const params = useParams<{ id: string }>();
  const visitId = params.id;
  const router = useRouter();
  const toast = useToast();
  const showError = useErrorScreen();
  const { L, lang } = useLang();

  const [summary, setSummary] = useState<VisitSummary | null>(null);
  const [etag, setEtag] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [dictating, setDictating] = useState<string | null>(null);
  const [dictSeconds, setDictSeconds] = useState(0);
  const [modifying, setModifying] = useState<GuidanceItem | null>(null);
  const [modText, setModText] = useState("");
  const [modCode, setModCode] = useState("");
  // إكمال تلقائي من السجل المرجعي (قرار مالك 2026-08-02) — GET /codes/search
  const [codeResults, setCodeResults] = useState<CodeSearchResult[]>([]);
  const [codeSearchOpen, setCodeSearchOpen] = useState(false);
  const codeSearchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const [transcript, setTranscript] = useState<TranscriptSegment[]>([]);
  const [transcriptLoaded, setTranscriptLoaded] = useState(false);
  const [conflict, setConflict] = useState<{ sectionId: string; mine: string } | null>(null);
  const [upload, setUpload] = useState<UploadView>({ phase: "idle" });
  const [voidOpen, setVoidOpen] = useState(false);
  const [voidReason, setVoidReason] = useState("wrong_patient");
  const [voidNote, setVoidNote] = useState("");
  const [voidBusy, setVoidBusy] = useState(false);
  // مسار Unlock للبوابة ① (قرار مالك 2026-08-03) — فتح المذكرة بسبب مسجّل قبل إتمام ②
  const [unlockOpen, setUnlockOpen] = useState(false);
  const [unlockReason, setUnlockReason] = useState("");
  const [unlockBusy, setUnlockBusy] = useState(false);
  // مسار Reopen (م6) — نسخة جديدة ببوابتين بعد النقل
  const [reopenOpen, setReopenOpen] = useState(false);
  const [reopenReason, setReopenReason] = useState("");
  const [reopenBusy, setReopenBusy] = useState(false);
  // مشغّل السند (م10): نقرة جملة → مقطعها الصوتي بسياق ±1ث + إبراز مقطع التفريغ
  const [player, setPlayer] = useState<{
    sectionId: string; index: number; startMs: number; endMs: number; segmentIds: string[];
  } | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const chatRef = useRef<HTMLDivElement | null>(null);
  const dictTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await apiWithHeaders<VisitSummary>(`/visits/${visitId}/summary`);
      setSummary(result.body.data);
      setEtag(result.body.data.etag);
      if (["approved", "uploaded", "upload_failed"].includes(result.body.data.state)) {
        const status = await api<UploadStatus>(`/visits/${visitId}/upload-status`);
        setUpload({ phase: "done", status: status.data });
      }
    } catch (err) {
      showError(err);
    }
    // نص المحادثة يُجلب مع التحميل: تفريغ فارغ = «لم يُلتقط صوت» — تمييزه عن فشل التحليل (W-224)
    try {
      const transcriptBody = await api<{ content: { segments: TranscriptSegment[] } }>(`/visits/${visitId}/transcript`);
      setTranscript(transcriptBody.data.content.segments ?? []);
      setTranscriptLoaded(true);
    } catch (err) {
      if (err instanceof ApiError && err.code === "MDF-4041") setTranscriptLoaded(true); // لا تفريغ لهذه الزيارة إطلاقاً
    }
  }, [visitId, showError]);

  useEffect(() => { void load(); }, [load]);

  const approvedLocked = summary !== null && ["approved", "uploaded", "upload_failed"].includes(summary.state);
  const voided = summary !== null && summary.state === "voided";
  const locked = approvedLocked || voided;                // المبطلة مختومة كالمعتمدة — قراءة فقط
  const noteApproved = summary?.note_approved ?? false;   // البوابة ① أُنجزت
  const canExport = summary?.can_export ?? false;         // البوابة ② أُنجزت
  const allGuidance = summary?.sections.flatMap((section) => section.guidance) ?? [];
  const counters = {
    pending: allGuidance.filter((item) => item.status === "pending").length,
    accepted: allGuidance.filter((item) => item.status === "accepted" || item.status === "modified").length,
    rejected: allGuidance.filter((item) => item.status === "rejected").length,
  };
  // A5: بند محسوم بكود محجوب دون العتبة يمنع البوابة ②
  const awaitingInput = summary?.awaiting_doctor_input_count ?? 0;
  // نص المذكرة يُحرَّر حتى البوابة ① فقط
  const noteEditable = summary !== null && !locked && !noteApproved;
  // تفريغ فارغ = الميكروفون لم يلتقط كلاماً — سببٌ أدق من «فشل التحليل» ويُعرض بدله
  const noAudio = summary !== null && transcriptLoaded && transcript.length === 0;
  const analysisFailed = summary !== null && allGuidance.length === 0 && summary.state === "in_review" && !noAudio;

  const handleMutationError = (err: unknown, sectionId?: string, mine?: string) => {
    if (err instanceof ApiError && err.code === "MDF-4224" && sectionId !== undefined && mine !== undefined) {
      setConflict({ sectionId, mine }); // W-222
      return;
    }
    if (err instanceof ApiError) toast(`${err.text(lang)} (${err.code})`);
    else showError(err);
  };

  const saveTyping = async (section: SummarySection) => {
    try {
      const result = await api<{ etag: string }>(`/summary-sections/${section.id}`, {
        method: "PATCH",
        headers: { "If-Match": etag },
        body: { content_current: editText },
      });
      setEtag(result.data.etag);
      setEditing(null);
      toast(L("حُفظت الفقرة — edit_event(typing) (FR-705)", "Section saved — edit_event(typing) (FR-705)"));
      void load();
    } catch (err) {
      handleMutationError(err, section.id, editText);
    }
  };

  const startDictation = (section: SummarySection) => {
    setDictating(section.id);
    setDictSeconds(0);
    dictTimer.current = setInterval(() => setDictSeconds((value) => value + 1), 1000);
  };

  const stopDictation = async (merge: boolean) => {
    if (dictTimer.current !== null) clearInterval(dictTimer.current);
    const sectionId = dictating;
    setDictating(null);
    if (!merge || sectionId === null) return;
    try {
      const result = await api<{ etag: string }>(`/summary-sections/${sectionId}/dictate`, {
        method: "POST",
        headers: { "If-Match": etag },
        body: { mode: "append" },
      });
      setEtag(result.data.etag);
      toast(L("دُمج الإملاء في الفقرة المحددة — edit_event(voice) (FR-706)", "Dictation merged into the selected section — edit_event(voice) (FR-706)"));
      void load();
    } catch (err) {
      handleMutationError(err, sectionId, "");
    }
  };

  const searchCodes = (item: GuidanceItem, query: string) => {
    setModCode(query);
    if (codeSearchTimer.current !== null) clearTimeout(codeSearchTimer.current);
    if (query.trim().length < 2) {
      setCodeResults([]);
      setCodeSearchOpen(false);
      return;
    }
    const system = item.code_system ?? "ICD10AM";
    codeSearchTimer.current = setTimeout(async () => {
      try {
        const result = await api<CodeSearchResult[]>(
          `/codes/search?system=${encodeURIComponent(system)}&q=${encodeURIComponent(query.trim())}`,
        );
        setCodeResults(result.data);
        setCodeSearchOpen(result.data.length > 0);
      } catch {
        setCodeResults([]);
        setCodeSearchOpen(false); // سجل غير محمّل أو خطأ عابر — يبقى الإدخال الحر متاحاً
      }
    }, 250);
  };

  const resolveGuidance = async (item: GuidanceItem, status: "accepted" | "rejected" | "modified") => {
    try {
      const body: Record<string, unknown> = { status };
      if (status === "modified") {
        body["modified_text"] = modText;
        body["modified_code_value"] = modCode || null;
        // كود محجوب دون العتبة: الطبيب يُدخله بنظام ICD-10-AM افتراضاً (يُتحقق قبل الرفع)
        body["modified_code_system"] = item.code_system ?? (item.requires_doctor_input ? "ICD10AM" : null);
      }
      await api(`/guidance-items/${item.id}`, { method: "PATCH", body });
      if (status === "accepted") toast(L("قُبل الإرشاد بفعل صريح (FR-704)", "Guidance item accepted by explicit action (FR-704)"));
      else if (status === "rejected") toast(L("رُفض الإرشاد — يبقى القرار مسجلاً", "Guidance item rejected — the decision stays on record"));
      else toast(L("حُفظ الإرشاد معدلاً — النص والرمز معاً — وقُبل (FR-704)", "Guidance item saved as modified — text and code together — and accepted (FR-704)"));
      setModifying(null);
      void load();
    } catch (err) {
      handleMutationError(err);
    }
  };

  const sendChat = async (message: string) => {
    if (message.trim().length === 0 || summary === null) return;
    setChat((current) => [...current, { who: "doctor", text: message }]);
    setChatInput("");
    setChatBusy(true);
    try {
      const result = await api<{ reply: string; patches: ChatPatch[]; etag: string }>(`/visits/${visitId}/ai-chat`, {
        method: "POST",
        body: { message, history: chat.map((entry) => ({ who: entry.who, text: entry.text })) },
      });
      setEtag(result.data.etag);
      setChat((current) => [...current, {
        who: "ai", text: result.data.reply, patches: result.data.patches,
        undone: result.data.patches.map(() => false),
      }]);
      if (result.data.patches.length > 0) void load();
      setTimeout(() => chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: "smooth" }), 100);
    } catch (err) {
      handleMutationError(err);
      setChat((current) => current.slice(0, -1));
    } finally {
      setChatBusy(false);
    }
  };

  const undoPatch = async (messageIndex: number, patchIndex: number) => {
    const message = chat[messageIndex];
    const patch = message?.patches?.[patchIndex];
    if (patch === undefined) return;
    try {
      const result = await api<{ etag: string }>(`/summary-sections/${patch.section_id}`, {
        method: "PATCH",
        headers: { "If-Match": etag },
        body: { content_current: patch.old_content },
      });
      setEtag(result.data.etag);
      setChat((current) => current.map((entry, index) => {
        if (index !== messageIndex || entry.undone === undefined) return entry;
        const undone = [...entry.undone];
        undone[patchIndex] = true;
        return { ...entry, undone };
      }));
      toast(L("تُرجع عن التعديل — قابل للتراجع قبل الاعتماد فقط", "Edit undone — reversible only before approval"));
      void load();
    } catch (err) {
      handleMutationError(err, patch.section_id, patch.old_content);
    }
  };

  const approve = async () => {
    if (summary === null) return;
    if (counters.pending > 0) {
      toast(L(`لا يمكن الاعتماد — ${counters.pending} إرشادات معلقة (MDF-4222)`,
              `Cannot approve — ${counters.pending} pending guidance items (MDF-4222)`));
      document.querySelector(".guidance-card.pending")?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    const withPendingText = summary.sections.find((section) => PENDING_TEXT.test(section.content_current));
    if (withPendingText !== undefined) {
      toast(L(`عنصر معلق [ ] في قسم ${withPendingText.section_key} — عالجه قبل الاعتماد`,
              `Pending item [ ] in section ${withPendingText.section_key} — resolve it before approval`));
      document.getElementById(`section-${withPendingText.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    // A5: كود محجوب دون العتبة يجب أن يُدخله الطبيب قبل اعتماد الأكواد
    if (awaitingInput > 0) {
      toast(L(`${awaitingInput} كود يتطلب إدخال الطبيب — لا تخمين قبل اعتماد الأكواد`,
              `${awaitingInput} code(s) require clinician input — no guessing before code approval`));
      document.querySelector(".guidance-card.needs-input")?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    setUpload({ phase: "uploading" });
    try {
      await api(`/visits/${visitId}/approve`, { method: "POST" });   // البوابة ②
      const status = await api<UploadStatus>(`/visits/${visitId}/upload-status`);
      setUpload({ phase: "done", status: status.data });
      void load();
    } catch (err) {
      setUpload({ phase: "idle" });
      handleMutationError(err);
      void load();
    }
  };

  // البوابة ① — اعتماد نص المذكرة (يجمّد النص، ويفتح حسم الأكواد)
  const approveNote = async () => {
    if (summary === null) return;
    const withPendingText = summary.sections.find((section) => PENDING_TEXT.test(section.content_current));
    if (withPendingText !== undefined) {
      toast(L(`عنصر معلق [ ] في قسم ${withPendingText.section_key} — عالجه قبل اعتماد النص`,
              `Pending item [ ] in section ${withPendingText.section_key} — resolve it before note approval`));
      document.getElementById(`section-${withPendingText.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    try {
      await api(`/visits/${visitId}/note-approve`, { method: "POST" });
      toast(L("اعتُمد نص المذكرة (البوابة ①) — انتقل لاعتماد الأكواد", "Note approved (gate ①) — proceed to code approval"));
      void load();
    } catch (err) {
      handleMutationError(err);
      void load();
    }
  };

  // فتح المذكرة — نقض البوابة ① قبل إتمام ② (قرار مالك 2026-08-03، حلقة CDI):
  // مراجعة الأكواد كشفت نقص توثيق → سبب مسجّل → تعديل → إعادة اعتماد. قرارات الأكواد محفوظة.
  const unlockNote = async () => {
    const reason = unlockReason.trim();
    if (reason.length === 0) return;
    setUnlockBusy(true);
    try {
      await api(`/visits/${visitId}/note-unlock`, { method: "POST", body: { reason } });
      setUnlockOpen(false);
      setUnlockReason("");
      toast(L("فُتحت المذكرة — عدّل النص ثم أعد اعتماده (البوابة ①). قرارات الأكواد محفوظة.",
              "Note unlocked — edit the text, then re-approve it (gate ①). Code decisions are preserved."));
      void load();
    } catch (err) {
      handleMutationError(err);
      void load();
    } finally {
      setUnlockBusy(false);
    }
  };

  // إبطال الزيارة من in_review (قرار مالك 2026-08-03) — Void ≠ Delete:
  // المحتوى يُختم ويخرج من المخارج والإحصائيات، وواقعة الإبطال تبقى في التدقيق
  const voidVisit = async () => {
    if (voidReason === "other" && voidNote.trim().length === 0) {
      toast(L("اختيار «سبب آخر» يتطلب توضيحاً نصياً", "Choosing \"other\" requires a written explanation"));
      return;
    }
    setVoidBusy(true);
    try {
      await api(`/visits/${visitId}/void`, {
        method: "POST",
        body: { reason: voidReason, note: voidNote.trim() },
      });
      setVoidOpen(false);
      toast(L("أُبطلت الزيارة — السبب والفاعل والوقت في سجل التدقيق، وهي خارج المخارج والإحصائيات",
              "Visit voided — reason, actor, and time are in the audit log; it is excluded from outputs and stats"));
      router.push("/doctor/visits");
    } catch (err) {
      handleMutationError(err);
    } finally {
      setVoidBusy(false);
    }
  };

  const copyForEmr = async () => {
    try {
      const result = await api<{ content: string }>(`/visits/${visitId}/export/text`);
      await navigator.clipboard.writeText(result.data.content);
      toast(L("نُسخت المذكرة — الصقها في نظام المستشفى", "Note copied — paste it into the hospital system"));
    } catch (err) {
      handleMutationError(err);
    }
  };

  // م6: إعادة فتح زيارة منقولة — نسخة جديدة ببوابتين (المبدأ 2: لا تحرير بعد النقل إلا هكذا)
  const reopenVisit = async () => {
    if (reopenReason.trim().length === 0) {
      toast(L("سبب إعادة الفتح إلزامي — يُسجّل مع النسخة الجديدة", "A reopen reason is required — recorded with the new version"));
      return;
    }
    setReopenBusy(true);
    try {
      const body = await api<{ state: string; version: number }>(`/visits/${visitId}/reopen`, {
        method: "POST",
        body: { reason: reopenReason.trim() },
      });
      setReopenOpen(false);
      setReopenReason("");
      setUpload({ phase: "idle" });
      toast(L(`فُتحت النسخة ${body.data.version} — النسخة السابقة منقولة ومجمّدة، وتلزم إعادة البوابتين`,
              `Version ${body.data.version} opened — the previous version is transferred and frozen; both gates are required again`));
      await load();
    } catch (err) {
      handleMutationError(err);
    } finally {
      setReopenBusy(false);
    }
  };

  const downloadPdf = async () => {
    // التوكن يُرسل كترويسة Bearer لا ككوكي، فلا يصلح window.open — نجلب PDF كـ blob بالمصادقة
    try {
      const token = getToken();
      const response = await fetch(`/api/v1/visits/${visitId}/export/pdf`, {
        headers: token !== null ? { Authorization: `Bearer ${token}` } : {},
        credentials: "include",
      });
      if (!response.ok) { toast(L("تعذّر توليد PDF", "Could not generate the PDF")); return; }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `medify-note-${visitId.slice(0, 8)}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch {
      toast(L("تعذّر توليد PDF", "Could not generate the PDF"));
    }
  };

  // م10: تشغيل سند جملة — بسياق ثانية قبل البداية وثانية بعد النهاية
  const playEvidence = (sectionId: string, index: number, sentence: EvidenceSentence) => {
    if (sentence.audio_start_ms === null || sentence.audio_end_ms === null) return;
    setPlayer({
      sectionId, index,
      startMs: sentence.audio_start_ms,
      endMs: sentence.audio_end_ms,
      segmentIds: sentence.segment_ids,
    });
  };

  useEffect(() => {
    const audio = audioRef.current;
    if (audio === null || player === null) return;
    const start = Math.max(0, player.startMs / 1000 - 1);
    const end = player.endMs / 1000 + 1;
    const stopAtEnd = () => { if (audio.currentTime >= end) audio.pause(); };
    audio.currentTime = start;
    void audio.play().catch(() => undefined); // حظر التشغيل التلقائي — يضغط الدكتور تشغيل يدوياً
    audio.addEventListener("timeupdate", stopAtEnd);
    return () => audio.removeEventListener("timeupdate", stopAtEnd);
  }, [player]);

  const retryUpload = async () => {
    setUpload({ phase: "uploading" });
    try {
      await api(`/visits/${visitId}/upload-retry`, { method: "POST" });
    } catch (err) {
      handleMutationError(err);
    }
    const status = await api<UploadStatus>(`/visits/${visitId}/upload-status`);
    setUpload({ phase: "done", status: status.data });
    void load();
  };

  const openTranscript = async () => {
    setTranscriptOpen(true);
    if (!transcriptLoaded) {
      try {
        const result = await api<{ content: { segments: TranscriptSegment[] } }>(`/visits/${visitId}/transcript`);
        setTranscript(result.data.content.segments ?? []);
        setTranscriptLoaded(true);
      } catch (err) {
        handleMutationError(err);
      }
    }
  };

  const stage = upload.phase === "uploading" ? 7
    : upload.phase === "done" && upload.status.status === "confirmed" ? 8
    : upload.phase === "done" && upload.status.status === "failed" ? 7
    : 6;
  const failStage = upload.phase === "done" && upload.status.status === "failed" ? 7 : undefined;

  if (summary === null) {
    return (
      <Shell title={L("مساحة المراجعة الموحدة", "Unified review workspace")}>
        <main className="page-wrap journey"><div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div></main>
      </Shell>
    );
  }

  return (
    <Shell title={L("مساحة المراجعة الموحدة", "Unified review workspace")}>
      <ProgressBar7 current={stage} failStage={failStage} />
      <main className="page-wrap journey" style={{ paddingBottom: 150 }}>
        <SpecBar ids="W-214 · W-215 · W-216 · W-217 · W-218 · W-219 · W-220 · W-222 · W-224" desc={L("الصفحة 15 — الصفحة المحورية", "Page 15 — the pivotal page")} />

        {/* رأس الزيارة */}
        <div className="card" style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <strong style={{ fontSize: 16 }}>{L("مراجعة الزيارة", "Visit review")}</strong>
          <bdi className="tech-badge">{visitId.slice(0, 8)}</bdi>
          <span style={{ fontSize: 12.5, color: "#5c7096" }}>{L("وُلّد بـ", "Generated with")} <bdi>{summary.model_ref}</bdi></span>
          <span style={{ flex: 1 }} />
          <span className="badge warn">{L("معلق", "Pending")} <span className="num">{counters.pending}</span></span>
          <span className="badge success">{L("مقبول", "Accepted")} <span className="num">{counters.accepted}</span></span>
          <span className="badge danger">{L("مرفوض", "Rejected")} <span className="num">{counters.rejected}</span></span>
          <button className="btn-row" onClick={() => void openTranscript()}>{L("نص المحادثة الكامل", "Full transcript")}</button>
          {approvedLocked ? (
            <span className="badge success">{L("🔒 معتمدة — قراءة فقط (MDF-4226)", "🔒 Approved — read-only (MDF-4226)")}</span>
          ) : voided ? (
            <span className="badge" style={{ background: "#fbeaea", color: "#a13333" }}>{L("⊘ مُبطلة — قراءة فقط", "⊘ Voided — read-only")}</span>
          ) : ["summarized", "in_review", "approved"].includes(summary.state) ? (
            // مصادر الإبطال الموسّعة (م4): قبل النقل — بعد النقل المسار reopen
            <button className="btn-danger-outline" style={{ height: 34 }} onClick={() => setVoidOpen(true)}
              title={L("زيارة لا يصح اعتمادها (مريض خطأ / مكررة / تجريبية / سحب موافقة) — إبطال بسبب مدوَّن في التدقيق",
                       "A visit that must not be approved (wrong patient / duplicate / test / consent withdrawn) — void with an audited reason")}>
              {L("⊘ إبطال الزيارة", "⊘ Void visit")}
            </button>
          ) : null}
        </div>

        {voided ? (
          <div style={{ border: "2px solid #a13333", background: "#fbeaea", borderRadius: 12, padding: "12px 16px", marginTop: 12, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <strong style={{ color: "#a13333" }}>⊘ {L("زيارة مُبطلة — لا اعتماد ولا رفع ولا تصدير", "Voided visit — no approval, no upload, no export")}</strong>
            <span style={{ fontSize: 12.5, color: "#5c7096" }}>
              {L("المحتوى محفوظ للقراءة فقط، والزيارة خارج المخارج والإحصائيات وملف المريض. سبب الإبطال وفاعله ووقته في سجل التدقيق (Void ≠ Delete)، والصوت يتبع سياسة الاحتفاظ ذاتها.",
                 "Content is kept read-only; the visit is excluded from outputs, statistics, and the patient file. The void reason, actor, and time are in the audit log (Void ≠ Delete), and audio follows the same retention policy.")}
            </span>
          </div>
        ) : null}

        {noAudio ? (
          <div style={{ border: "2px solid #d94b4b", background: "#fbeaea", borderRadius: 12, padding: "12px 16px", marginTop: 12, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <strong style={{ color: "#a13333" }}>⚠ {L("لم يُلتقط أي كلام مسموع في تسجيل هذه الزيارة", "No audible speech was captured in this visit's recording")}</strong>
            <span style={{ fontSize: 12.5, color: "#5c7096" }}>
              {L("الميكروفون لم يُوصِل صوتاً، لذلك الملخص فارغ ولا نص محادثة ولا إرشادات — لا يُلخَّص كلام لم يُقَل. تحقق من الميكروفون (الكتم/الجهاز الصحيح) وابدأ زيارة جديدة.",
                 "The microphone delivered no audio, so the summary is empty with no transcript and no guidance — speech never said is never summarized. Check the microphone (mute/correct device) and start a new visit.")}
            </span>
          </div>
        ) : null}

        {analysisFailed ? (
          <div style={{ border: "2px solid #9c6f00", background: "#fdf4e0", borderRadius: 12, padding: "12px 16px", marginTop: 12, display: "flex", gap: 10, alignItems: "center" }}>
            <SpecBadge id="W-224" />
            <strong style={{ color: "#9c6f00" }}>{L("فشل التحليل الذكي", "AI analysis failed")} (<bdi>MDF-5033</bdi>)</strong>
            <span style={{ fontSize: 12.5, color: "#5c7096" }}>
              {L("الملخص متاح بلا إرشادات — المراجعة والاعتماد متاحان، وسجّلنا إشعاراً بذلك.",
                 "The summary is available without guidance — review and approval remain available, and a notification was logged.")}
            </span>
          </div>
        ) : null}

        {/* م11: شريط جودة الصوت — الدرجة الإجمالية دون العتبة الدنيا */}
        {summary.stt_confidence.mean !== null
          && summary.stt_confidence.mean < summary.stt_confidence.thresholds.low ? (
          <div className="card" style={{ marginTop: 12, borderInlineStart: "4px solid var(--m-warn)",
                                         background: "var(--m-warn-bg)", display: "flex", gap: 10,
                                         alignItems: "center", flexWrap: "wrap" }}>
            <strong style={{ color: "var(--m-warn)" }}>
              {L("جودة الصوت منخفضة — راجع بعناية", "Low audio quality — review carefully")}
            </strong>
            <span style={{ fontSize: 12.5, color: "#5c7096", flex: 1 }}>
              {L("متوسط ثقة التفريغ لهذه الزيارة دون العتبة. الجمل المبرزة أدناه هي الأقل ثقة — اسمع مصادرها قبل الاعتماد.",
                 "Average transcription confidence for this visit is below the threshold. The highlighted sentences are the least confident — listen to their sources before approving.")}
            </span>
          </div>
        ) : null}

        {/* لافتة النسخة الجديدة (م6): reopen جارٍ — السابقة منقولة ومجمّدة */}
        {summary.version > 1 && summary.state === "in_review" ? (
          <div className="card" style={{ marginTop: 12, borderInlineStart: "4px solid var(--m-info)",
                                         display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <span className="badge info">{L(`النسخة ${summary.version} قيد الإعداد`, `Version ${summary.version} in progress`)}</span>
            <span style={{ fontSize: 12.5, color: "#5c7096", flex: 1 }}>
              {L(`النسخة ${summary.version - 1} منقولة ومجمّدة لدى المستشفى — هذه النسخة تستبدلها بعد إعادة البوابتين (① بنقرة إن لم يتغيّر النص، و② كاملة).`,
                 `Version ${summary.version - 1} is transferred and frozen at the hospital — this version replaces it after both gates (① one-click if the text is unchanged, ② in full).`)}
              {(() => {
                const current = summary.versions.find((row) => row.version_number === summary.version);
                return current?.reopen_reason
                  ? " " + L(`سبب الفتح: «${current.reopen_reason}»`, `Reopen reason: "${current.reopen_reason}"`)
                  : "";
              })()}
            </span>
          </div>
        ) : null}

        {/* بطاقات الأقسام — ديناميكياً من القالب */}
        {summary.sections.map((section) => {
          const pendingText = PENDING_TEXT.test(section.content_current);
          const titlePair = SECTION_TITLES[section.section_key];
          const title = titlePair !== undefined ? L(titlePair.ar, titlePair.en) : section.section_key;
          return (
            <section key={section.id} id={`section-${section.id}`} className="card" style={{ marginTop: 14 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <span style={{ width: 34, height: 34, borderRadius: 8, background: "#005a55", color: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", fontWeight: 800 }}>
                  <bdi className="ui">{section.section_key}</bdi>
                </span>
                <strong style={{ fontSize: 16, flex: 1 }}>{title}</strong>
                {section.is_edited ? <span className="badge info">{L("معدّل", "Modified")}</span> : null}
                {pendingText && noteEditable ? (
                  <button className="badge warn" style={{ border: "none", cursor: "pointer", animation: "mPulseW 2.2s ease infinite" }}
                    title={L("نص بين قوسين معلقين لم يُحسم — عالجه قبل الاعتماد", "Unresolved bracketed text — resolve it before approval")}
                    onClick={() => { setEditing(section.id); setEditText(section.content_current); }}>
                    {L("⚠ عنصر معلق [ ] — عالجه", "⚠ Pending item [ ] — resolve it")}
                  </button>
                ) : null}
                {noteEditable && editing !== section.id && dictating !== section.id ? (
                  <span style={{ display: "inline-flex", gap: 6 }}>
                    <button className="btn-row" onClick={() => { setEditing(section.id); setEditText(section.content_current); }}>{L("✏ كتابة", "✏ Type")}</button>
                    <button className="btn-row" onClick={() => startDictation(section)}>{L("🎤 إملاء صوتي", "🎤 Voice dictation")}</button>
                    <button className="btn-row" onClick={() => document.getElementById("ai-chat")?.scrollIntoView({ behavior: "smooth" })}>{L("💬 محادثة AI", "💬 AI chat")}</button>
                  </span>
                ) : null}
              </div>

              {editing === section.id ? (
                <div style={{ border: "1.5px solid #00736d", borderRadius: 10, padding: 12, marginTop: 10 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 700, color: "#005a55", marginBottom: 6 }}>
                    {L("وضع التحرير الكتابي", "Typing edit mode")} <SpecBadge id="W-215" /> {L("— يسجّل", "— logs")} <bdi>edit_event(typing)</bdi>
                  </div>
                  <textarea className="field clinical" rows={5} value={editText} dir="ltr"
                    onChange={(event) => setEditText(event.target.value)} />
                  <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                    <button className="btn-success" style={{ height: 38 }} onClick={() => void saveTyping(section)}>{L("حفظ الفقرة", "Save section")}</button>
                    <button className="btn-neutral" style={{ height: 38 }} onClick={() => setEditing(null)}>{L("إلغاء", "Cancel")}</button>
                  </div>
                </div>
              ) : dictating === section.id ? (
                <div style={{ marginTop: 10 }}>
                  <p className="clinical" style={{ opacity: 0.45, margin: "6px 0" }}>{section.content_current}</p>
                  <div style={{ background: "#d6f5f2", borderRadius: 10, padding: "10px 14px", display: "flex", alignItems: "center", gap: 12 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 999, background: "#d94b4b", animation: "mBlink 1.2s ease infinite" }} />
                    <span style={{ fontSize: 14 }}>{L("جارٍ الاستماع للإملاء… تحدّث الآن", "Listening for dictation… speak now")}</span>
                    <bdi>{String(Math.floor(dictSeconds / 60)).padStart(2, "0")}:{String(dictSeconds % 60).padStart(2, "0")}</bdi>
                    <span className="wave" style={{ height: 22 }}>
                      {Array.from({ length: 5 }, (_, index) => <span key={index} style={{ animationDelay: `${index * 0.12}s` }} />)}
                    </span>
                    <span style={{ flex: 1 }} />
                    <button className="btn-success" style={{ height: 36 }} onClick={() => void stopDictation(true)}>{L("إيقاف ودمج النص", "Stop & merge text")}</button>
                    <button className="btn-neutral" style={{ height: 36 }} onClick={() => void stopDictation(false)}>{L("إلغاء", "Cancel")}</button>
                  </div>
                  <p style={{ fontSize: 12.5, color: "#5c7096", margin: "6px 0 0" }}>
                    <SpecBadge id="W-216" /> {L("مسار قصير غير متدفق بنموذج P1 نفسه — يُدمج في الفقرة المحددة (FR-706).",
                                                "Short non-streaming path on the same P1 model — merged into the selected section (FR-706).")}
                  </p>
                </div>
              ) : section.evidence !== null && section.evidence.length > 0 ? (
                // م10: عرض جملةً بجملة — نقرة الجملة المسنودة تشغّل مقطعها الصوتي (±1ث)
                <p className="clinical" style={{ margin: "10px 0 0", lineHeight: 2.1 }}>
                  {section.evidence.map((sentence, index) => {
                    const hasAudio = sentence.audio_start_ms !== null && sentence.segment_ids.length > 0;
                    const isActive = player !== null && player.sectionId === section.id && player.index === index;
                    // م11: درجتان بصريتان — دون low إبراز قوي، وبينها وbين medium إبراز خفيف
                    const conf = sentence.confidence;
                    const thresholds = summary.stt_confidence.thresholds;
                    const confClass = conf === null ? ""
                      : conf < thresholds.low ? " conf-low"
                      : conf < thresholds.medium ? " conf-medium" : "";
                    return (
                      <span key={index}
                        className={`ev-sentence${hasAudio ? " has-audio" : ""}${isActive ? " active" : ""}${confClass}`}
                        onClick={hasAudio ? () => playEvidence(section.id, index, sentence) : undefined}
                        title={confClass !== ""
                          ? L("ثقة تفريغ منخفضة — اسمع المصدر", "Low transcription confidence — listen to the source")
                          : hasAudio
                            ? L("اسمع المقطع المصدر من المحادثة (±1 ثانية سياق)", "Play the source segment from the conversation (±1s context)")
                            : undefined}>
                        {sentence.text}
                        {hasAudio ? <span className="ev-icon" aria-hidden>🎧</span> : null}
                        {!hasAudio && sentence.origin === "ai" ? (
                          <span className="ev-tag">{L("بلا مصدر صوتي", "No audio source")}</span>
                        ) : null}
                        {sentence.origin === "doctor" ? (
                          <span className="ev-tag doctor">{L("تحرير طبيب", "Clinician edit")}</span>
                        ) : null}
                        {" "}
                      </span>
                    );
                  })}
                </p>
              ) : (
                <p className="clinical" style={{ margin: "10px 0 0", whiteSpace: "pre-wrap" }}>{section.content_current}</p>
              )}

              {player !== null && player.sectionId === section.id ? (
                <div className="ev-player">
                  <span aria-hidden>🎧</span>
                  <audio ref={audioRef} controls preload="metadata"
                    src={`/api/v1/visits/${visitId}/audio?token=${encodeURIComponent(getToken() ?? "")}`}
                    style={{ flex: 1, height: 34 }} />
                  <span style={{ fontSize: 11.5, color: "#5c7096" }}>
                    {L("المقطع المصدر مُبرز في نص المحادثة الكامل", "The source segment is highlighted in the full transcript")}
                  </span>
                  <button className="btn-row" onClick={() => { audioRef.current?.pause(); setPlayer(null); }}>
                    {L("إغلاق", "Close")}
                  </button>
                </div>
              ) : null}

              {section.guidance.length > 0 ? (
                <div style={{ borderTop: "1px dashed #c7d1e0", marginTop: 12, paddingTop: 10 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 700, color: "#5c7096" }}>
                    {L("إرشادات هذه الفقرة", "Guidance for this section")} (<span className="num">{section.guidance.length}</span>) {L("— مضمّنة على الفقرة التي تخصها فقط", "— inline on its own section only")}
                  </div>
                  {section.guidance.map((item) => {
                    const status = STATUS_META[item.status];
                    const kind = KIND_META[item.kind];
                    const needsInput = item.requires_doctor_input === true;
                    const cardClass = needsInput && item.status !== "rejected"
                      ? "guidance-card needs-input"
                      : item.status === "pending" ? "guidance-card pending" : "guidance-card";
                    const confidencePct = typeof item.confidence === "number" ? Math.round(item.confidence * 100) : null;
                    return (
                      <div key={item.id} className={cardClass}>
                        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                          <span className="badge" style={{ background: status.bg, color: status.fg }}>{L(status.label.ar, status.label.en)}</span>
                          <span className="badge" style={{ background: kind.bg, color: kind.fg }}>{L(kind.label.ar, kind.label.en)}</span>
                          {item.safety_flag && item.status === "pending" ? (
                            <span className="badge safety">{L("⚠ سلامة مريض — بانتظار الحسم", "⚠ Patient safety — awaiting resolution")}</span>
                          ) : null}
                          {item.registry_status === "inactive" ? (
                            <span className="badge" style={{ background: "#fbeaea", color: "#d94b4b", border: "1px dashed #d94b4b" }}
                              title={L("الكود ملغى في السجل المرجعي — لن يمر من بوابة الاعتماد ② حتى يُستبدل", "The code is retired in the reference registry — it will not pass approval gate 2 until replaced")}>
                              {L("⚠ كود ملغى", "⚠ Retired code")}
                              {item.code_replaced_by ? <> — {L("البديل:", "Replacement:")} <bdi className="ui">{item.code_replaced_by}</bdi></> : null}
                            </span>
                          ) : null}
                          <span style={{ flex: 1 }} />
                          {needsInput ? (
                            <span className="badge" style={{ background: "#fdf4e0", color: "#9c6f00", border: "1px dashed #d8b24a" }}
                              title={L("درجة الثقة دون العتبة — لا يُعرض كود مقترح، أدخله يدوياً", "Confidence below threshold — no suggested code shown; enter it manually")}>
                              {L("⚠ يتطلب إدخال الطبيب", "⚠ Requires clinician input")}
                              {confidencePct !== null ? <> · <bdi className="ui">{confidencePct}%</bdi></> : null}
                            </span>
                          ) : item.code_value !== null ? (
                            <span className="code-badge" title={
                              (item.code_registry_version ?? "") + (item.code_effective_date ? ` · ${item.code_effective_date}` : "")
                              + (item.registry_status === "valid" ? L(" · مُتحقق من السجل المرجعي", " · verified against the reference registry") : "")
                            }>
                              {item.code_system} · {item.code_value}
                              {item.registry_status === "valid" ? <span style={{ color: "#12a594" }}> ✓</span> : null}
                              {item.code_secondary_value ? <> · {item.code_secondary_system} {item.code_secondary_value}</> : null}
                              {confidencePct !== null ? <span style={{ opacity: 0.7 }}> · <bdi className="ui">{confidencePct}%</bdi></span> : null}
                            </span>
                          ) : null}
                        </div>
                        <p className="clinical" style={{ margin: "8px 0 4px" }}>{item.suggestion_text}</p>
                        {item.linked_dx_code || item.justification ? (
                          <div style={{ fontSize: 12, color: "#5c7096", display: "flex", flexDirection: "column", gap: 2, marginBottom: 4 }}>
                            {item.linked_dx_code ? <span>{L("مرتبط بتشخيص:", "Linked Dx:")} <bdi className="ui">{item.linked_dx_code}</bdi></span> : null}
                            {item.justification ? <span>{L("المبرر:", "Justification:")} {item.justification}</span> : null}
                          </div>
                        ) : null}
                        <div style={{ fontSize: 12.5, color: "#5c7096", display: "flex", flexDirection: "column", gap: 2 }}>
                          <span>{L("🕐 المصدر:", "🕐 Source:")} {item.evidence_source === "patient_file" ? L("من ملف المريض", "From the patient file") : L("من كلام الزيارة", "From the visit conversation")} — {item.evidence_ref ?? "—"}</span>
                          {needsInput ? (
                            <span style={{ color: "#9c6f00" }}>
                              {L("«لا تخمين»: أدخل الكود بنفسك عبر «تعديل» — أو ارفض البند.",
                                 "\"No guessing\": enter the code yourself via \"Modify\" — or reject the item.")}
                            </span>
                          ) : null}
                        </div>
                        {modifying?.id === item.id ? (
                          <div style={{ marginTop: 8 }}>
                            {item.code_system !== null || needsInput ? (
                              <>
                                <label className="field-label" style={{ fontSize: 12.5 }}>
                                  {needsInput
                                    ? L("أدخل الرمز يدوياً (كان محجوباً دون عتبة الثقة)", "Enter the code manually (it was withheld below the confidence threshold)")
                                    : <>{L("الرمز —", "Code —")} {item.code_system} {L("(يُتحقق منه مقابل النظام النشط قبل الرفع)", "(validated against the active system before upload)")}</>}
                                </label>
                                <div style={{ position: "relative" }}>
                                  <input className="field mono" value={modCode} onChange={(event) => searchCodes(item, event.target.value)}
                                    placeholder={needsInput ? L("ابحث بالكود أو الوصف — مثال: I10", "Search by code or description — e.g. I10") : ""} />
                                  {codeSearchOpen && codeResults.length > 0 ? (
                                    <div style={{ position: "absolute", top: "100%", insetInlineStart: 0, insetInlineEnd: 0, zIndex: 30,
                                      background: "#fff", border: "1px solid #c7d1e0", borderRadius: 10,
                                      boxShadow: "0 8px 24px rgba(16,42,67,.14)", maxHeight: 220, overflowY: "auto" }}>
                                      {codeResults.map((result) => (
                                        <button key={result.code} type="button"
                                          disabled={!result.is_active && result.replaced_by === null}
                                          title={result.long_desc ?? result.short_desc}
                                          onClick={() => {
                                            if (result.is_active) { setModCode(result.code); setCodeSearchOpen(false); }
                                            else if (result.replaced_by !== null) searchCodes(item, result.replaced_by);
                                          }}
                                          style={{ display: "flex", gap: 8, alignItems: "baseline", width: "100%", textAlign: "start",
                                            padding: "8px 10px", background: "transparent", border: "none",
                                            borderBottom: "1px solid #eef2f7", cursor: "pointer",
                                            opacity: result.is_active ? 1 : 0.6 }}>
                                          <bdi className="ui" style={{ fontWeight: 700, fontSize: 12.5, whiteSpace: "nowrap" }}>{result.code}</bdi>
                                          <span style={{ fontSize: 12.5, color: "#33475f", flex: 1 }} dir="ltr">{result.short_desc}</span>
                                          {!result.is_active ? (
                                            <span style={{ fontSize: 11.5, color: "#d94b4b", whiteSpace: "nowrap" }}>
                                              {L("ملغى", "Retired")}
                                              {result.replaced_by !== null ? <> ← <bdi className="ui">{result.replaced_by}</bdi></> : null}
                                            </span>
                                          ) : null}
                                        </button>
                                      ))}
                                    </div>
                                  ) : null}
                                </div>
                              </>
                            ) : null}
                            <label className="field-label" style={{ fontSize: 12.5 }}>{L("نص الإرشاد", "Guidance text")}</label>
                            <textarea className="field clinical" rows={3} dir="ltr" value={modText} onChange={(event) => setModText(event.target.value)} />
                            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                              <button className="btn-success" style={{ height: 36 }} onClick={() => void resolveGuidance(item, "modified")}>{L("حفظ وقبول معدلاً", "Save & accept as modified")}</button>
                              <button className="btn-neutral" style={{ height: 36 }} onClick={() => setModifying(null)}>{L("إلغاء", "Cancel")}</button>
                            </div>
                          </div>
                        ) : item.status === "pending" && !locked ? (
                          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                            <button className="btn-success" style={{ height: 36 }} onClick={() => void resolveGuidance(item, "accepted")}>{L("قبول", "Accept")}</button>
                            <button className="btn-danger-outline" style={{ height: 36 }} onClick={() => void resolveGuidance(item, "rejected")}>{L("رفض", "Reject")}</button>
                            <button className="btn-row" onClick={() => { setModifying(item); setModText(item.suggestion_text); setModCode(item.code_value ?? ""); setCodeResults([]); setCodeSearchOpen(false); }}>{L("تعديل", "Modify")}</button>
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </section>
          );
        })}

        {/* محادثة AI الختامية W-217 */}
        <section id="ai-chat" className="card" style={{ marginTop: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <strong style={{ fontSize: 16, flex: 1 }}>{L("محادثة AI الختامية", "Final AI chat")}</strong>
            <SpecBadge id="W-217" />
          </div>
          <p style={{ fontSize: 12.5, color: "#5c7096", margin: "4px 0 10px" }}>
            {L("تعدّل الملخص فقط — لا وقائع سريرية جديدة، والغموض سؤال توضيحي (DOC-15 §٥).",
               "Edits the summary only — no new clinical facts; ambiguity becomes a clarifying question (DOC-15 §5).")}
          </p>
          <div ref={chatRef} style={{ maxHeight: 340, overflowY: "auto", display: "flex", flexDirection: "column" }}>
            {chat.map((message, messageIndex) => (
              <div key={messageIndex}>
                <div className={message.who === "doctor" ? "chat-msg doctor" : "chat-msg ai"}>{message.text}</div>
                {message.patches?.map((patch, patchIndex) => (
                  <div key={patch.section_id + String(patchIndex)} style={{ border: "1px solid #c7d1e0", borderRadius: 10, padding: 10, marginBottom: 10, maxWidth: "88%" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, fontWeight: 700 }}>
                      {L("بطاقة فرق — قسم", "Diff card — section")} <bdi>{patch.section_key}</bdi>
                      <span style={{ color: "#5c7096", fontWeight: 400 }}>{L("تعليم ما تغيّر (FR-707)", "Highlights what changed (FR-707)")}</span>
                      <span style={{ flex: 1 }} />
                      {message.undone?.[patchIndex] === true ? (
                        <span className="badge neutral">{L("تم التراجع", "Undone")}</span>
                      ) : noteEditable ? (
                        <button className="btn-danger-outline" style={{ height: 30, padding: "0 12px", fontSize: 12.5 }}
                          onClick={() => void undoPatch(messageIndex, patchIndex)}>{L("تراجع", "Undo")}</button>
                      ) : null}
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 8 }}>
                      <div style={{ background: "#fbeaea", borderRadius: 8, padding: 8 }}>
                        <div style={{ fontSize: 12.5, fontWeight: 700, color: "#d94b4b" }}>{L("قبل", "Before")}</div>
                        <div className="clinical" style={{ color: "#d94b4b", textDecoration: "line-through", fontSize: 12.5 }}>
                          {patch.old_content.length > 0 ? patch.old_content : L("— (لم يكن موجوداً)", "— (did not exist)")}
                        </div>
                      </div>
                      <div style={{ background: "#e6f7f4", borderRadius: 8, padding: 8 }}>
                        <div style={{ fontSize: 12.5, fontWeight: 700, color: "#12a594" }}>{L("بعد", "After")}</div>
                        <div className="clinical" style={{ color: "#12a594", fontWeight: 700, fontSize: 12.5 }}>{patch.new_content}</div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ))}
            {chatBusy ? <div className="chat-msg ai"><span className="spinner dark" /> {L("يعالج طلبك…", "Processing your request…")}</div> : null}
          </div>
          {noteEditable ? (
            <>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "10px 0" }}>
                <button className="pill" onClick={() => void sendChat(L("اجعل المتابعة بعد أسبوع بدل أسبوعين", "Make the follow-up in one week instead of two"))}>{L("اجعل المتابعة بعد أسبوع بدل أسبوعين", "Make the follow-up in one week instead of two")}</button>
                <button className="pill" onClick={() => void sendChat(L("أضف إلى الخطة قياس الضغط المنزلي مرتين يومياً مع تسجيل القراءات.", "Add home blood pressure measurement twice daily with recorded readings to the plan."))}>{L("أضف قياس الضغط المنزلي للخطة", "Add home BP monitoring to the plan")}</button>
              </div>
              <form style={{ display: "flex", gap: 8 }} onSubmit={(event) => { event.preventDefault(); void sendChat(chatInput); }}>
                <input className="field" placeholder={L("اكتب أي طلب تعديل على الملخص…", "Type any edit request for the summary…")} value={chatInput}
                  onChange={(event) => setChatInput(event.target.value)} style={{ flex: 1 }} />
                <button type="submit" className="btn" disabled={chatBusy}>{L("إرسال", "Send")}</button>
              </form>
            </>
          ) : noteApproved && !locked ? (
            <p style={{ fontSize: 12.5, color: "#9c6f00", margin: "8px 0 0", display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <span style={{ flex: 1 }}>
                {L("🔒 اعتُمد نص المذكرة (البوابة ①) — التحرير مغلق. حسم الأكواد لا يزال متاحاً أدناه.",
                   "🔒 Note approved (gate ①) — editing is closed. Code resolution remains available below.")}
              </span>
              {/* حلقة CDI: كود يحتاج سنداً ناقصاً في النص؟ فتح بسبب مسجّل بدل كود بلا سند */}
              <button className="btn-secondary" style={{ height: 30, padding: "0 12px", fontSize: 12.5 }} onClick={() => setUnlockOpen(true)}
                title={L("الكود المقترح يتطلب تفصيلاً لا يذكره النص المجمّد؟ افتح المذكرة بسبب مسجّل، عدّل، ثم أعد الاعتماد",
                         "The suggested code needs a detail the frozen text lacks? Unlock with an audited reason, edit, then re-approve")}>
                {L("🔓 فتح المذكرة", "🔓 Unlock note")}
              </button>
            </p>
          ) : null}
          <p style={{ fontSize: 12.5, color: "#5c7096", margin: "10px 0 0" }}>
            {L("كل تعديل يسجّل", "Every edit logs an")} <bdi>edit_event</bdi> {L("بقناته — كتابة / صوت / محادثة (DOC-04 §٥).", "with its channel — typing / voice / chat (DOC-04 §5).")}
          </p>
        </section>
      </main>

      {/* شريط الاعتماد الثابت — بوابتان ①② (توجيه المالك 2026-07-22) + حالة الرفع W-219 */}
      <div style={{ position: "fixed", bottom: 0, insetInline: 0, zIndex: 45, background: "#fff", borderTop: "1px solid #c7d1e0", boxShadow: "0 -8px 24px rgba(12,26,54,.08)" }}>
        <div style={{ maxWidth: 960, margin: "0 auto", padding: "12px 20px", display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <SpecBadge id={upload.phase === "idle" ? "W-218" : "W-219"} />
          {/* زيارة مُبطلة — لا بوابات ولا رفع */}
          {voided ? (
            <span style={{ display: "flex", alignItems: "center", gap: 10, flex: 1, flexWrap: "wrap" }}>
              <span className="badge" style={{ background: "#fbeaea", color: "#a13333" }}>{L("⊘ مُبطلة", "⊘ Voided")}</span>
              <span style={{ fontSize: 12.5, color: "#5c7096" }}>
                {L("البوابتان مغلقتان — القرار مسجّل في سجل التدقيق", "Both gates are closed — the decision is recorded in the audit log")}
              </span>
              <span style={{ flex: 1 }} />
              <button className="btn-secondary" onClick={() => router.push("/doctor/visits")}>{L("سجل الزيارات", "Visit log")}</button>
            </span>
          ) : null}
          {/* زيارة معتمدة/منقولة محمّلة من جديد — قراءة فقط + مسار reopen (م6) */}
          {upload.phase === "idle" && approvedLocked && summary !== null ? (
            <span style={{ display: "flex", alignItems: "center", gap: 10, flex: 1, flexWrap: "wrap" }}>
              <span className={`badge ${summary.state === "upload_failed" ? "danger" : "success"}`}>
                {summary.state === "uploaded"
                  ? L(`منقولة ✓ — النسخة ${summary.versions.filter(v => v.upload_status === "uploaded").length || 1}`,
                      `Uploaded ✓ — version ${summary.versions.filter(v => v.upload_status === "uploaded").length || 1}`)
                  : summary.state === "upload_failed"
                    ? L("فشل الرفع — أعد المحاولة (نفس النسخة، بلا بوابات)", "Upload failed — retry (same version, no gates)")
                    : L("معتمدة — بانتظار الرفع", "Approved — awaiting upload")}
              </span>
              <span style={{ flex: 1 }} />
              {canExport ? <ExportButtons L={L} onPdf={() => void downloadPdf()} onCopy={() => void copyForEmr()} /> : null}
              {summary.state === "upload_failed" ? (
                <button className="btn" onClick={() => void retryUpload()}>{L("إعادة محاولة الرفع", "Retry upload")}</button>
              ) : null}
              {summary.state === "uploaded" ? (
                <button className="btn-secondary" onClick={() => setReopenOpen(true)}
                  title={L("تعديل بعد النقل؟ نسخة جديدة ببوابتين تستبدل السابقة لدى المستشفى (replace) — السابقة تبقى مجمّدة",
                           "Editing after transfer? A new version with both gates replaces the previous one at the hospital — the old version stays frozen")}>
                  {L("↺ إعادة فتح — نسخة جديدة", "↺ Reopen — new version")}
                </button>
              ) : null}
            </span>
          ) : null}
          {/* مؤشر البوابتين */}
          {upload.phase === "idle" && !locked ? (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 700 }}>
              <span className="badge" style={{ background: noteApproved ? "#e6f7f4" : "#eef2f7", color: noteApproved ? "#12a594" : "#5c7096" }}>
                {noteApproved ? "✓" : "①"} {L("نص المذكرة", "Note")}
              </span>
              <span style={{ color: "#c7d1e0" }}>←</span>
              <span className="badge" style={{ background: "#eef2f7", color: "#5c7096" }}>
                {"②"} {L("الأكواد", "Codes")}
              </span>
            </span>
          ) : null}
          {/* البوابة ① — اعتماد نص المذكرة (أو إعادة اعتماده بعد فتح بمسار Unlock) */}
          {upload.phase === "idle" && !locked && !noteApproved ? (
            <>
              <span style={{ fontSize: 12.5, color: summary.note_unlock !== null ? "#9c6f00" : "#5c7096", fontWeight: 700, flex: 1 }}>
                {summary.note_unlock !== null
                  ? summary.note_unlock.text_unchanged
                    ? L(`فُتحت المذكرة — السبب: «${summary.note_unlock.reason}». النص لم يتغيّر منذ الاعتماد المنقوض (البصمة مطابقة) — أعد الاعتماد بنقرة واحدة أو عدّل أولاً.`,
                        `Note unlocked — reason: "${summary.note_unlock.reason}". The text is unchanged since the revoked approval (hash matches) — re-approve with one click, or edit first.`)
                    : L(`فُتحت المذكرة بعد نقض الاعتماد — السبب: «${summary.note_unlock.reason}». النص تغيّر؛ راجعه ثم أعد اعتماده (①). قرارات الأكواد السابقة محفوظة.`,
                        `Note unlocked after revoking approval — reason: "${summary.note_unlock.reason}". The text changed; review it, then re-approve (①). Previous code decisions are preserved.`)
                  : L("راجع نص المذكرة ثم اعتمده (البوابة ①). بعدها يتجمّد النص ويُفتح حسم الأكواد.",
                      "Review the note text, then approve it (gate ①). The text then freezes and code resolution opens.")}
              </span>
              <button className="btn-success btn-approve" onClick={() => void approveNote()}>
                {summary.note_unlock !== null
                  ? summary.note_unlock.text_unchanged
                    ? L("① إعادة الاعتماد — النص لم يتغيّر", "① Re-approve — text unchanged")
                    : L("① إعادة اعتماد النص", "① Re-approve note")
                  : L("① اعتماد نص المذكرة", "① Approve note")}
              </button>
            </>
          ) : null}
          {/* البوابة ② — اعتماد الأكواد ثم الرفع */}
          {upload.phase === "idle" && !locked && noteApproved ? (
            <>
              <span style={{ fontSize: 12.5, color: counters.pending === 0 && awaitingInput === 0 ? "#12a594" : "#9c6f00", fontWeight: 700, flex: 1 }}>
                {counters.pending > 0
                  ? L(`${counters.pending} إرشادات معلقة — احسمها قبل اعتماد الأكواد (MDF-4222)`,
                      `${counters.pending} pending guidance items — resolve them before code approval (MDF-4222)`)
                  : awaitingInput > 0
                    ? L(`${awaitingInput} كود محجوب يتطلب إدخال الطبيب — لا تخمين`,
                        `${awaitingInput} withheld code(s) require clinician input — no guessing`)
                    : L("جاهزة لاعتماد الأكواد · بالاعتماد تُرفع الزيارة FHIR/NPHIES ويُتاح التصدير (FR-802)",
                        "Ready for code approval · Approval uploads the visit (FHIR/NPHIES) and unlocks export (FR-802)")}
              </span>
              {/* مسار Unlock: متاح فقط في مرحلة ② قبل إتمامها — بعد الاعتماد النهائي المسار Addendum */}
              <button className="btn-secondary" onClick={() => setUnlockOpen(true)}
                title={L("كود يتطلب تفصيلاً لا يذكره النص المجمّد (جهة، مع/بدون مضاعفات…)؟ افتح المذكرة بسبب مسجّل",
                         "A code needs a detail the frozen text lacks (laterality, with/without complications…)? Unlock with an audited reason")}>
                {L("🔓 فتح المذكرة", "🔓 Unlock note")}
              </button>
              <button className="btn-success btn-approve" disabled={counters.pending > 0 || awaitingInput > 0} onClick={() => void approve()}>
                {L("② اعتماد الأكواد والرفع", "② Approve codes & upload")}
              </button>
            </>
          ) : null}
          {upload.phase === "uploading" ? (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 10, flex: 1 }}>
              <span className="spinner dark" /> {L("جارٍ الرفع لنظام المستشفى —", "Uploading to the hospital system —")} <bdi>Bundle FHIR/NPHIES</bdi>…
            </span>
          ) : null}
          {upload.phase === "done" ? (
            upload.status.status === "confirmed" ? (
              <span style={{ display: "flex", alignItems: "center", gap: 10, flex: 1, flexWrap: "wrap" }}>
                <span className="badge success">{L("رفع ناجح ✓ مؤكد confirmed", "Upload successful ✓ confirmed")}</span>
                <span style={{ fontSize: 12.5, color: "#5c7096" }}>
                  {L("المحاولات:", "Attempts:")} <span className="num">{upload.status.attempts_count}</span> {L("· التحقق البنيوي NPHIES: مجتاز ✓", "· NPHIES structural validation: passed ✓")}
                </span>
                <span style={{ flex: 1 }} />
                {canExport ? <ExportButtons L={L} onPdf={() => void downloadPdf()} onCopy={() => void copyForEmr()} /> : null}
                <button className="btn-secondary" onClick={() => router.push("/doctor/visits")}>{L("سجل الزيارات", "Visit log")}</button>
              </span>
            ) : (
              <span style={{ display: "flex", alignItems: "center", gap: 10, flex: 1, flexWrap: "wrap" }}>
                <span className="badge danger">{L("فشل الرفع", "Upload failed")}</span>
                <span style={{ fontSize: 12.5, color: "#5c7096" }}>
                  <bdi>{upload.status.attempts[upload.status.attempts.length - 1]?.error_code ?? "MDF-5052"}</bdi>
                  {L("· المحاولات:", "· Attempts:")} <span className="num">{upload.status.attempts_count}</span> {L("— أُشعر الأدمن (ad.upload_failed)", "— admin notified (ad.upload_failed)")}
                </span>
                <span style={{ flex: 1 }} />
                {/* وضع الجسر: حتى لو فشل الرفع للمستشفى، التصدير متاح بعد البوابة ② */}
                {canExport ? <ExportButtons L={L} onPdf={() => void downloadPdf()} onCopy={() => void copyForEmr()} /> : null}
                <button className="btn" onClick={() => void retryUpload()}>{L("إعادة المحاولة", "Retry")}</button>
              </span>
            )
          ) : null}
        </div>
        {/* شريط التصدير — وضع الجسر: مخرجات يوم-واحد قبل اكتمال التكامل (A3) */}
        {canExport ? (
          <div style={{ maxWidth: 960, margin: "0 auto", padding: "0 20px 10px", fontSize: 11.5, color: "#5c7096" }}>
            {L("التصدير متاح بعد البوابة ② — PDF بترويسة المنشأة أو نسخ نصي نظيف للـ EMR (وضع الجسر قبل اكتمال التكامل).",
               "Export available after gate ② — PDF with the facility letterhead or a clean text copy for the EMR (bridge mode before full integration).")}
          </div>
        ) : null}
      </div>

      {/* لوح النص الكامل W-220 */}
      {transcriptOpen ? (
        <>
          <div className="drawer-overlay" onClick={() => setTranscriptOpen(false)} />
          <div className="drawer">
            <div style={{ padding: "14px 16px", borderBottom: "1px solid #c7d1e0", display: "flex", alignItems: "center", gap: 8 }}>
              <strong style={{ flex: 1 }}>{L("نص المحادثة الكامل", "Full transcript")}</strong>
              <SpecBadge id="W-220" />
              <button className="modal-close" aria-label={L("إغلاق", "Close")} onClick={() => setTranscriptOpen(false)}>✕</button>
            </div>
            <div style={{ padding: "6px 16px", fontSize: 12.5, color: "#5c7096", borderBottom: "1px solid #d6f5f2" }}>
              {L("محفوظ مرتبطاً بالزيارة (FR-604) · الصوت يُحذف آلياً وفق سياسة الاحتفاظ",
                 "Stored linked to the visit (FR-604) · Audio is auto-deleted per the retention policy")}
            </div>
            <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
              {transcript.length === 0 ? (
                <div className="grid-empty" style={{ textAlign: "center" }}>
                  {L("لا يوجد نص محادثة لهذه الزيارة — لم يُلتقط كلام مسموع في التسجيل.",
                     "No transcript for this visit — no audible speech was captured in the recording.")}<br />
                  <span style={{ fontSize: 12.5 }}>
                    {L("غالباً الميكروفون كان مكتوماً أو التُقط جهاز خاطئ. تحقق منه وابدأ زيارة جديدة.",
                       "Most likely the microphone was muted or the wrong device was captured. Check it and start a new visit.")}
                  </span>
                </div>
              ) : transcript.map((segment) => (
                <div key={segment.id}
                  className={player !== null && player.segmentIds.includes(segment.id) ? "tr-highlight" : undefined}
                  style={{ marginBottom: 10, fontSize: 14, lineHeight: 1.9 }}>
                  <SpeakerBadge speaker={segment.speaker} confidence={segment.speaker_confidence} />{" "}
                  <bdi className="tech-badge">{segment.t0.toFixed(0)}s</bdi> {segment.text}
                </div>
              ))}
            </div>
          </div>
        </>
      ) : null}

      {/* مودال الإبطال — سبب من قائمة + نص حر، كله إلى سجل التدقيق (قرار مالك 2026-08-03) */}
      {voidOpen ? (
        <Modal title={L("إبطال الزيارة", "Void visit")} onClose={() => setVoidOpen(false)}>
          <p style={{ fontSize: 14, color: "#5c7096", marginTop: 0 }}>
            {L("للزيارة التي لا يصح اعتمادها. الإبطال نهائي: لا اعتماد ولا رفع ولا تصدير، وتخرج من الإحصائيات وملف المريض. يبقى في سجل التدقيق: من أبطل، ولماذا، ومتى (Void ≠ Delete).",
               "For a visit that must not be approved. Voiding is final: no approval, upload, or export, and it leaves the statistics and the patient file. The audit log keeps who voided it, why, and when (Void ≠ Delete).")}
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {VOID_REASONS.map((reason) => (
              <label key={reason.key} style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", fontSize: 14 }}>
                <input type="radio" name="void-reason" checked={voidReason === reason.key}
                  onChange={() => setVoidReason(reason.key)} />
                {L(reason.ar, reason.en)}
              </label>
            ))}
          </div>
          <label className="field-label" style={{ fontSize: 12.5, marginTop: 10 }}>
            {voidReason === "other"
              ? L("التوضيح — إلزامي مع «سبب آخر»", "Explanation — required with \"other\"")
              : L("توضيح إضافي (اختياري) — يُدوَّن في سجل التدقيق", "Additional note (optional) — recorded in the audit log")}
          </label>
          <textarea className="field" rows={2} maxLength={500} value={voidNote}
            onChange={(event) => setVoidNote(event.target.value)}
            placeholder={L("بيان إداري لا محتوى سريرياً", "Administrative note, no clinical content")} />
          <div className="modal-actions">
            <button className="btn-danger" disabled={voidBusy} onClick={() => void voidVisit()}>
              {voidBusy ? L("جارٍ الإبطال…", "Voiding…") : L("⊘ تأكيد الإبطال", "⊘ Confirm void")}
            </button>
            <button className="btn-neutral" onClick={() => setVoidOpen(false)}>{L("تراجع", "Back")}</button>
          </div>
        </Modal>
      ) : null}

      {/* مودال فتح المذكرة — نقض البوابة ① بسبب مسجّل (قرار مالك 2026-08-03، حلقة CDI) */}
      {unlockOpen ? (
        <Modal title={L("فتح المذكرة — نقض اعتماد النص ①", "Unlock note — revoke note approval ①")} onClose={() => setUnlockOpen(false)}>
          <p style={{ fontSize: 14, color: "#5c7096", marginTop: 0 }}>
            {L("مراجعة الأكواد كشفت نقص توثيق؟ (جهة الإصابة، مع/بدون مضاعفات…) — القاعدة الذهبية: الكود لازم يسنده التوثيق. الفتح يُلغي اعتماد البوابة ① ويعيد التحرير، ثم تعيد اعتماد النص وترجع للأكواد. قراراتك المحسومة على الأكواد تبقى محفوظة. متاح قبل إتمام البوابة ② فقط — بعد الاعتماد النهائي المسار ملحق (Addendum).",
               "Code review revealed missing documentation? (laterality, with/without complications…) — the golden rule: the code must be supported by the documentation. Unlocking revokes gate ① and reopens editing; then you re-approve the note and return to the codes. Your resolved code decisions are preserved. Available only before gate ② is completed — after final approval the path is an addendum.")}
          </p>
          <label className="field-label" style={{ fontSize: 12.5 }}>
            {L("سبب الفتح — إلزامي، يُدوَّن في سجل التدقيق", "Unlock reason — required, recorded in the audit trail")}
          </label>
          <textarea className="field" rows={3} maxLength={2000} value={unlockReason}
            onChange={(event) => setUnlockReason(event.target.value)}
            placeholder={L("مثال: كود الكسر يتطلب تحديد الجهة (يمين/يسار) والنص لا يذكرها", "e.g., the fracture code requires laterality (right/left) and the note does not mention it")} />
          <div className="modal-actions">
            <button className="btn" disabled={unlockBusy || unlockReason.trim().length === 0} onClick={() => void unlockNote()}>
              {unlockBusy ? L("جارٍ الفتح…", "Unlocking…") : L("🔓 فتح المذكرة وإلغاء اعتماد ①", "🔓 Unlock note & revoke gate ①")}
            </button>
            <button className="btn-neutral" onClick={() => setUnlockOpen(false)}>{L("تراجع", "Back")}</button>
          </div>
        </Modal>
      ) : null}

      {/* مودال إعادة الفتح (م6) — نسخة جديدة ببوابتين تستبدل المنقولة */}
      {reopenOpen ? (
        <Modal title={L("إعادة فتح — نسخة جديدة تستبدل المنقولة", "Reopen — a new version replacing the transferred one")} onClose={() => setReopenOpen(false)}>
          <p style={{ fontSize: 14, color: "#5c7096", marginTop: 0 }}>
            {L("التحرير حصراً داخل Medify: تُفتح نسخة جديدة تنسخ الأخيرة، تعدّلها ثم تعيد البوابتين (① بنقرة إن لم يتغيّر النص، و② كاملة)، فتُنقل بدلالة استبدال (replace) تستهدف وثيقة Medify السابقة حصراً. النسخة المنقولة تبقى مجمّدة حرفياً لدى الطرفين. عطل تقني في الرفع؟ استخدم «إعادة محاولة الرفع» لا إعادة الفتح.",
               "Editing happens only inside Medify: a new version copies the last one; you edit it, redo both gates (① one-click if the text is unchanged, ② in full), and it transfers with replace semantics targeting the previous Medify document only. The transferred version stays frozen verbatim on both sides. Technical upload failure? Use “Retry upload”, not reopen.")}
          </p>
          <label className="field-label" style={{ fontSize: 12.5 }}>
            {L("سبب إعادة الفتح — إلزامي، يُخزَّن مع النسخة الجديدة", "Reopen reason — required, stored with the new version")}
          </label>
          <textarea className="field" rows={3} maxLength={2000} value={reopenReason}
            onChange={(event) => setReopenReason(event.target.value)}
            placeholder={L("مثال: وصلت نتيجة مختبر تغيّر التقييم والخطة", "e.g., a lab result arrived that changes the assessment and plan")} />
          <div className="modal-actions">
            <button className="btn" disabled={reopenBusy || reopenReason.trim().length === 0} onClick={() => void reopenVisit()}>
              {reopenBusy ? L("جارٍ الفتح…", "Reopening…") : L("↺ فتح نسخة جديدة", "↺ Open a new version")}
            </button>
            <button className="btn-neutral" onClick={() => setReopenOpen(false)}>{L("تراجع", "Back")}</button>
          </div>
        </Modal>
      ) : null}

      {/* تعارض ETag W-222 */}
      {conflict !== null ? (
        <Modal title={L("تعارض تحرير — نسخة أحدث موجودة (MDF-4224)", "Edit conflict — a newer version exists (MDF-4224)")} spec="W-222" onClose={() => setConflict(null)} wide>
          <p style={{ fontSize: 14, color: "#5c7096" }}>{L("عُدّل هذا الملخص من جلسة أخرى. قارن النسختين واختر:", "This summary was edited from another session. Compare the versions and choose:")}</p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div className="sub-box">
              <div style={{ fontSize: 12.5, fontWeight: 700, marginBottom: 6 }}>{L("نسختك (غير المحفوظة)", "Your version (unsaved)")}</div>
              <div className="clinical" style={{ fontSize: 12.5 }}>{conflict.mine}</div>
            </div>
            <div className="sub-box" style={{ borderColor: "#00736d" }}>
              <div style={{ fontSize: 12.5, fontWeight: 700, marginBottom: 6 }}>{L("نسخة الخادم (الأحدث)", "Server version (newest)")}</div>
              <div className="clinical" style={{ fontSize: 12.5 }}>
                {summary.sections.find((section) => section.id === conflict.sectionId)?.content_current ?? "…"}
              </div>
            </div>
          </div>
          <div className="modal-actions">
            <button className="btn" onClick={() => { setConflict(null); void load(); toast(L("اعتُمدت نسخة الخادم", "Server version kept")); }}>
              {L("اعتماد نسخة الخادم", "Keep the server version")}
            </button>
            <button className="btn-secondary" onClick={async () => {
              const fresh = await apiWithHeaders<VisitSummary>(`/visits/${visitId}/summary`);
              setEtag(fresh.body.data.etag);
              try {
                const result = await api<{ etag: string }>(`/summary-sections/${conflict.sectionId}`, {
                  method: "PATCH",
                  headers: { "If-Match": fresh.body.data.etag },
                  body: { content_current: conflict.mine },
                });
                setEtag(result.data.etag);
                toast(L("كُتبت نسختك فوق نسخة الخادم", "Your version overwrote the server version"));
              } catch (err) {
                handleMutationError(err);
              }
              setConflict(null);
              void load();
            }}>{L("الإبقاء على نسختي", "Keep my version")}</button>
          </div>
        </Modal>
      ) : null}
    </Shell>
  );
}
