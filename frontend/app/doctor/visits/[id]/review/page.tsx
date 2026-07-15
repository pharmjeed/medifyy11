"use client";

/** الصفحة 15 — مساحة المراجعة الموحدة (المحورية):
 *  W-214 الأقسام + الإرشادات المضمّنة · W-215 تحرير كتابي · W-216 إملاء صوتي · W-217 محادثة AI ·
 *  W-218 بوابة الاعتماد · W-219 حالة الرفع · W-220 النص الكامل · W-222 تعارض ETag · W-224 فشل التحليل.
 *  الأقسام تُبنى ديناميكياً من بنية القالب — لا S/O/A/P مثبتة (قرار مالك 2026-07-14). */

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, apiWithHeaders } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import type {
  ChatPatch, GuidanceItem, SummarySection, TranscriptSegment, UploadStatus, VisitSummary,
} from "@/lib/types";
import { ProgressBar7 } from "@/components/ProgressBar7";
import { Shell } from "@/components/Shell";
import { Modal, SpecBadge, SpecBar, useErrorScreen, useToast } from "@/components/ui";

const SECTION_TITLES: Record<string, { ar: string; en: string }> = {
  S: { ar: "الذاتي — Subjective", en: "Subjective" },
  O: { ar: "الموضوعي — Objective", en: "Objective" },
  A: { ar: "التقييم — Assessment", en: "Assessment" },
  P: { ar: "الخطة — Plan", en: "Plan" },
  E: { ar: "تثقيف المريض — Patient education", en: "Patient education" },
  H: { ar: "التاريخ المرضي — History", en: "History" },
};

const KIND_META: Record<GuidanceItem["kind"], { label: { ar: string; en: string }; bg: string; fg: string }> = {
  coding_match: { label: { ar: "ترميزي", en: "Coding" }, bg: "rgba(42,111,151,.12)", fg: "#2A6F97" },
  clinical_dx: { label: { ar: "سريري — تشخيص", en: "Clinical — diagnosis" }, bg: "#EAF6F7", fg: "#0A5C64" },
  clinical_rx: { label: { ar: "سريري — دواء", en: "Clinical — medication" }, bg: "#EAF6F7", fg: "#0A5C64" },
  clinical_procedure: { label: { ar: "سريري — إجراء", en: "Clinical — procedure" }, bg: "#EAF6F7", fg: "#0A5C64" },
};

const STATUS_META: Record<GuidanceItem["status"], { label: { ar: string; en: string }; bg: string; fg: string }> = {
  pending: { label: { ar: "معلق", en: "Pending" }, bg: "#FDF3E3", fg: "#B07D10" },
  accepted: { label: { ar: "مقبول", en: "Accepted" }, bg: "#E8F6EE", fg: "#2E9E5B" },
  rejected: { label: { ar: "مرفوض", en: "Rejected" }, bg: "#FDEEEE", fg: "#C0392B" },
  modified: { label: { ar: "مقبول — معدّل", en: "Accepted — modified" }, bg: "#E8F6EE", fg: "#2E9E5B" },
};

const PENDING_TEXT = /\[[^\]]*\]/;

interface ChatMessage { who: "doctor" | "ai"; text: string; patches?: ChatPatch[]; undone?: boolean[] }

type UploadView = { phase: "idle" } | { phase: "uploading" } | { phase: "done"; status: UploadStatus };

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
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const [transcript, setTranscript] = useState<TranscriptSegment[]>([]);
  const [conflict, setConflict] = useState<{ sectionId: string; mine: string } | null>(null);
  const [upload, setUpload] = useState<UploadView>({ phase: "idle" });
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
  }, [visitId, showError]);

  useEffect(() => { void load(); }, [load]);

  const locked = summary !== null && ["approved", "uploaded", "upload_failed"].includes(summary.state);
  const allGuidance = summary?.sections.flatMap((section) => section.guidance) ?? [];
  const counters = {
    pending: allGuidance.filter((item) => item.status === "pending").length,
    accepted: allGuidance.filter((item) => item.status === "accepted" || item.status === "modified").length,
    rejected: allGuidance.filter((item) => item.status === "rejected").length,
  };
  const analysisFailed = summary !== null && allGuidance.length === 0 && summary.state === "in_review";

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

  const resolveGuidance = async (item: GuidanceItem, status: "accepted" | "rejected" | "modified") => {
    try {
      const body: Record<string, unknown> = { status };
      if (status === "modified") {
        body["modified_text"] = modText;
        body["modified_code_value"] = modCode || null;
        body["modified_code_system"] = item.code_system;
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
    setUpload({ phase: "uploading" });
    try {
      await api(`/visits/${visitId}/approve`, { method: "POST" });
      const status = await api<UploadStatus>(`/visits/${visitId}/upload-status`);
      setUpload({ phase: "done", status: status.data });
      void load();
    } catch (err) {
      setUpload({ phase: "idle" });
      handleMutationError(err);
      void load();
    }
  };

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
    if (transcript.length === 0) {
      try {
        const result = await api<{ content: { segments: TranscriptSegment[] } }>(`/visits/${visitId}/transcript`);
        setTranscript(result.data.content.segments);
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
          <span style={{ fontSize: 12.5, color: "#5B7280" }}>{L("وُلّد بـ", "Generated with")} <bdi>{summary.model_ref}</bdi></span>
          <span style={{ flex: 1 }} />
          <span className="badge warn">{L("معلق", "Pending")} <span className="num">{counters.pending}</span></span>
          <span className="badge success">{L("مقبول", "Accepted")} <span className="num">{counters.accepted}</span></span>
          <span className="badge danger">{L("مرفوض", "Rejected")} <span className="num">{counters.rejected}</span></span>
          <button className="btn-row" onClick={() => void openTranscript()}>{L("نص المحادثة الكامل", "Full transcript")}</button>
          {locked ? (
            <span className="badge success">{L("🔒 معتمدة — قراءة فقط (MDF-4226)", "🔒 Approved — read-only (MDF-4226)")}</span>
          ) : null}
        </div>

        {analysisFailed ? (
          <div style={{ border: "2px solid #B07D10", background: "#FDF3E3", borderRadius: 12, padding: "12px 16px", marginTop: 12, display: "flex", gap: 10, alignItems: "center" }}>
            <SpecBadge id="W-224" />
            <strong style={{ color: "#B07D10" }}>{L("فشل التحليل الذكي", "AI analysis failed")} (<bdi>MDF-5033</bdi>)</strong>
            <span style={{ fontSize: 12.5, color: "#5B7280" }}>
              {L("الملخص متاح بلا إرشادات — المراجعة والاعتماد متاحان، وسجّلنا إشعاراً بذلك.",
                 "The summary is available without guidance — review and approval remain available, and a notification was logged.")}
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
                <span style={{ width: 34, height: 34, borderRadius: 8, background: "#0A5C64", color: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", fontWeight: 800 }}>
                  <bdi className="ui">{section.section_key}</bdi>
                </span>
                <strong style={{ fontSize: 16, flex: 1 }}>{title}</strong>
                {section.is_edited ? <span className="badge info">{L("معدّل", "Modified")}</span> : null}
                {pendingText && !locked ? (
                  <button className="badge warn" style={{ border: "none", cursor: "pointer", animation: "mPulseW 2.2s ease infinite" }}
                    title={L("نص بين قوسين معلقين لم يُحسم — عالجه قبل الاعتماد", "Unresolved bracketed text — resolve it before approval")}
                    onClick={() => { setEditing(section.id); setEditText(section.content_current); }}>
                    {L("⚠ عنصر معلق [ ] — عالجه", "⚠ Pending item [ ] — resolve it")}
                  </button>
                ) : null}
                {!locked && editing !== section.id && dictating !== section.id ? (
                  <span style={{ display: "inline-flex", gap: 6 }}>
                    <button className="btn-row" onClick={() => { setEditing(section.id); setEditText(section.content_current); }}>{L("✏ كتابة", "✏ Type")}</button>
                    <button className="btn-row" onClick={() => startDictation(section)}>{L("🎤 إملاء صوتي", "🎤 Voice dictation")}</button>
                    <button className="btn-row" onClick={() => document.getElementById("ai-chat")?.scrollIntoView({ behavior: "smooth" })}>{L("💬 محادثة AI", "💬 AI chat")}</button>
                  </span>
                ) : null}
              </div>

              {editing === section.id ? (
                <div style={{ border: "1.5px solid #0E7C86", borderRadius: 10, padding: 12, marginTop: 10 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 700, color: "#0A5C64", marginBottom: 6 }}>
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
                  <div style={{ background: "#EAF6F7", borderRadius: 10, padding: "10px 14px", display: "flex", alignItems: "center", gap: 12 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 999, background: "#C0392B", animation: "mBlink 1.2s ease infinite" }} />
                    <span style={{ fontSize: 14 }}>{L("جارٍ الاستماع للإملاء… تحدّث الآن", "Listening for dictation… speak now")}</span>
                    <bdi>{String(Math.floor(dictSeconds / 60)).padStart(2, "0")}:{String(dictSeconds % 60).padStart(2, "0")}</bdi>
                    <span className="wave" style={{ height: 22 }}>
                      {Array.from({ length: 5 }, (_, index) => <span key={index} style={{ animationDelay: `${index * 0.12}s` }} />)}
                    </span>
                    <span style={{ flex: 1 }} />
                    <button className="btn-success" style={{ height: 36 }} onClick={() => void stopDictation(true)}>{L("إيقاف ودمج النص", "Stop & merge text")}</button>
                    <button className="btn-neutral" style={{ height: 36 }} onClick={() => void stopDictation(false)}>{L("إلغاء", "Cancel")}</button>
                  </div>
                  <p style={{ fontSize: 12.5, color: "#5B7280", margin: "6px 0 0" }}>
                    <SpecBadge id="W-216" /> {L("مسار قصير غير متدفق بنموذج P1 نفسه — يُدمج في الفقرة المحددة (FR-706).",
                                                "Short non-streaming path on the same P1 model — merged into the selected section (FR-706).")}
                  </p>
                </div>
              ) : (
                <p className="clinical" style={{ margin: "10px 0 0", whiteSpace: "pre-wrap" }}>{section.content_current}</p>
              )}

              {section.guidance.length > 0 ? (
                <div style={{ borderTop: "1px dashed #D7E3E8", marginTop: 12, paddingTop: 10 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 700, color: "#5B7280" }}>
                    {L("إرشادات هذه الفقرة", "Guidance for this section")} (<span className="num">{section.guidance.length}</span>) {L("— مضمّنة على الفقرة التي تخصها فقط", "— inline on its own section only")}
                  </div>
                  {section.guidance.map((item) => {
                    const status = STATUS_META[item.status];
                    const kind = KIND_META[item.kind];
                    return (
                      <div key={item.id} className={item.status === "pending" ? "guidance-card pending" : "guidance-card"}>
                        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                          <span className="badge" style={{ background: status.bg, color: status.fg }}>{L(status.label.ar, status.label.en)}</span>
                          <span className="badge" style={{ background: kind.bg, color: kind.fg }}>{L(kind.label.ar, kind.label.en)}</span>
                          {item.safety_flag && item.status === "pending" ? (
                            <span className="badge safety">{L("⚠ سلامة مريض — بانتظار الحسم", "⚠ Patient safety — awaiting resolution")}</span>
                          ) : null}
                          <span style={{ flex: 1 }} />
                          {item.code_value !== null ? (
                            <span className="code-badge">{item.code_system} · {item.code_value}</span>
                          ) : null}
                        </div>
                        <p className="clinical" style={{ margin: "8px 0 4px" }}>{item.suggestion_text}</p>
                        <div style={{ fontSize: 12.5, color: "#5B7280", display: "flex", flexDirection: "column", gap: 2 }}>
                          <span>{L("🕐 المصدر:", "🕐 Source:")} {item.evidence_source === "patient_file" ? L("من ملف المريض", "From the patient file") : L("من كلام الزيارة", "From the visit conversation")} — {item.evidence_ref ?? "—"}</span>
                        </div>
                        {modifying?.id === item.id ? (
                          <div style={{ marginTop: 8 }}>
                            {item.code_system !== null ? (
                              <>
                                <label className="field-label" style={{ fontSize: 12.5 }}>{L("الرمز —", "Code —")} {item.code_system} {L("(يُتحقق منه مقابل النظام النشط قبل الرفع)", "(validated against the active system before upload)")}</label>
                                <input className="field mono" value={modCode} onChange={(event) => setModCode(event.target.value)} />
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
                            <button className="btn-row" onClick={() => { setModifying(item); setModText(item.suggestion_text); setModCode(item.code_value ?? ""); }}>{L("تعديل", "Modify")}</button>
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
          <p style={{ fontSize: 12.5, color: "#5B7280", margin: "4px 0 10px" }}>
            {L("تعدّل الملخص فقط — لا وقائع سريرية جديدة، والغموض سؤال توضيحي (DOC-15 §٥).",
               "Edits the summary only — no new clinical facts; ambiguity becomes a clarifying question (DOC-15 §5).")}
          </p>
          <div ref={chatRef} style={{ maxHeight: 340, overflowY: "auto", display: "flex", flexDirection: "column" }}>
            {chat.map((message, messageIndex) => (
              <div key={messageIndex}>
                <div className={message.who === "doctor" ? "chat-msg doctor" : "chat-msg ai"}>{message.text}</div>
                {message.patches?.map((patch, patchIndex) => (
                  <div key={patch.section_id + String(patchIndex)} style={{ border: "1px solid #D7E3E8", borderRadius: 10, padding: 10, marginBottom: 10, maxWidth: "88%" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, fontWeight: 700 }}>
                      {L("بطاقة فرق — قسم", "Diff card — section")} <bdi>{patch.section_key}</bdi>
                      <span style={{ color: "#5B7280", fontWeight: 400 }}>{L("تعليم ما تغيّر (FR-707)", "Highlights what changed (FR-707)")}</span>
                      <span style={{ flex: 1 }} />
                      {message.undone?.[patchIndex] === true ? (
                        <span className="badge neutral">{L("تم التراجع", "Undone")}</span>
                      ) : !locked ? (
                        <button className="btn-danger-outline" style={{ height: 30, padding: "0 12px", fontSize: 12.5 }}
                          onClick={() => void undoPatch(messageIndex, patchIndex)}>{L("تراجع", "Undo")}</button>
                      ) : null}
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 8 }}>
                      <div style={{ background: "#FDEEEE", borderRadius: 8, padding: 8 }}>
                        <div style={{ fontSize: 12.5, fontWeight: 700, color: "#C0392B" }}>{L("قبل", "Before")}</div>
                        <div className="clinical" style={{ color: "#C0392B", textDecoration: "line-through", fontSize: 12.5 }}>
                          {patch.old_content.length > 0 ? patch.old_content : L("— (لم يكن موجوداً)", "— (did not exist)")}
                        </div>
                      </div>
                      <div style={{ background: "#E8F6EE", borderRadius: 8, padding: 8 }}>
                        <div style={{ fontSize: 12.5, fontWeight: 700, color: "#2E9E5B" }}>{L("بعد", "After")}</div>
                        <div className="clinical" style={{ color: "#2E9E5B", fontWeight: 700, fontSize: 12.5 }}>{patch.new_content}</div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ))}
            {chatBusy ? <div className="chat-msg ai"><span className="spinner dark" /> {L("يعالج طلبك…", "Processing your request…")}</div> : null}
          </div>
          {!locked ? (
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
          ) : null}
          <p style={{ fontSize: 12.5, color: "#5B7280", margin: "10px 0 0" }}>
            {L("كل تعديل يسجّل", "Every edit logs an")} <bdi>edit_event</bdi> {L("بقناته — كتابة / صوت / محادثة (DOC-04 §٥).", "with its channel — typing / voice / chat (DOC-04 §5).")}
          </p>
        </section>
      </main>

      {/* شريط الاعتماد الثابت W-218 + حالة الرفع W-219 */}
      <div style={{ position: "fixed", bottom: 0, insetInline: 0, zIndex: 45, background: "#fff", borderTop: "1px solid #D7E3E8", boxShadow: "0 -8px 24px rgba(15,34,51,.08)" }}>
        <div style={{ maxWidth: 960, margin: "0 auto", padding: "12px 20px", display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <SpecBadge id={upload.phase === "idle" ? "W-218" : "W-219"} />
          {upload.phase === "idle" && !locked ? (
            <>
              <span style={{ fontSize: 12.5, color: counters.pending === 0 ? "#2E9E5B" : "#B07D10", fontWeight: 700, flex: 1 }}>
                {counters.pending === 0
                  ? L("صفر إرشادات معلقة — جاهزة للاعتماد · بالاعتماد تُرفع بيانات الزيارة كاملة بصيغة FHIR/NPHIES (FR-802)",
                      "Zero pending guidance — ready for approval · Approval uploads the full visit data in FHIR/NPHIES format (FR-802)")
                  : L(`${counters.pending} إرشادات معلقة — الاعتماد لا يتفعل إلا بصفر معلق (MDF-4222)`,
                      `${counters.pending} pending guidance items — approval unlocks only at zero pending (MDF-4222)`)}
              </span>
              <button className="btn-success btn-approve" disabled={counters.pending > 0} onClick={() => void approve()}>
                {L("اعتمد وارفع", "Approve & upload")}
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
                <span style={{ fontSize: 12.5, color: "#5B7280" }}>
                  {L("المحاولات:", "Attempts:")} <span className="num">{upload.status.attempts_count}</span> {L("· التحقق البنيوي NPHIES: مجتاز ✓", "· NPHIES structural validation: passed ✓")}
                </span>
                <span style={{ flex: 1 }} />
                <button className="btn-secondary" onClick={() => router.push("/doctor/visits")}>{L("سجل الزيارات", "Visit log")}</button>
              </span>
            ) : (
              <span style={{ display: "flex", alignItems: "center", gap: 10, flex: 1, flexWrap: "wrap" }}>
                <span className="badge danger">{L("فشل الرفع", "Upload failed")}</span>
                <span style={{ fontSize: 12.5, color: "#5B7280" }}>
                  <bdi>{upload.status.attempts[upload.status.attempts.length - 1]?.error_code ?? "MDF-5052"}</bdi>
                  {L("· المحاولات:", "· Attempts:")} <span className="num">{upload.status.attempts_count}</span> {L("— أُشعر الأدمن (ad.upload_failed)", "— admin notified (ad.upload_failed)")}
                </span>
                <span style={{ flex: 1 }} />
                <button className="btn" onClick={() => void retryUpload()}>{L("إعادة المحاولة", "Retry")}</button>
              </span>
            )
          ) : null}
        </div>
      </div>

      {/* لوح النص الكامل W-220 */}
      {transcriptOpen ? (
        <>
          <div className="drawer-overlay" onClick={() => setTranscriptOpen(false)} />
          <div className="drawer">
            <div style={{ padding: "14px 16px", borderBottom: "1px solid #D7E3E8", display: "flex", alignItems: "center", gap: 8 }}>
              <strong style={{ flex: 1 }}>{L("نص المحادثة الكامل", "Full transcript")}</strong>
              <SpecBadge id="W-220" />
              <button className="modal-close" aria-label={L("إغلاق", "Close")} onClick={() => setTranscriptOpen(false)}>✕</button>
            </div>
            <div style={{ padding: "6px 16px", fontSize: 12.5, color: "#5B7280", borderBottom: "1px solid #EAF6F7" }}>
              {L("محفوظ مرتبطاً بالزيارة (FR-604) · الصوت يُحذف آلياً وفق سياسة الاحتفاظ",
                 "Stored linked to the visit (FR-604) · Audio is auto-deleted per the retention policy")}
            </div>
            <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
              {transcript.map((segment) => (
                <div key={segment.id} style={{ marginBottom: 10, fontSize: 14, lineHeight: 1.9 }}>
                  <bdi className="tech-badge">{segment.t0.toFixed(0)}s</bdi> {segment.text}
                </div>
              ))}
            </div>
          </div>
        </>
      ) : null}

      {/* تعارض ETag W-222 */}
      {conflict !== null ? (
        <Modal title={L("تعارض تحرير — نسخة أحدث موجودة (MDF-4224)", "Edit conflict — a newer version exists (MDF-4224)")} spec="W-222" onClose={() => setConflict(null)} wide>
          <p style={{ fontSize: 14, color: "#5B7280" }}>{L("عُدّل هذا الملخص من جلسة أخرى. قارن النسختين واختر:", "This summary was edited from another session. Compare the versions and choose:")}</p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div className="sub-box">
              <div style={{ fontSize: 12.5, fontWeight: 700, marginBottom: 6 }}>{L("نسختك (غير المحفوظة)", "Your version (unsaved)")}</div>
              <div className="clinical" style={{ fontSize: 12.5 }}>{conflict.mine}</div>
            </div>
            <div className="sub-box" style={{ borderColor: "#0E7C86" }}>
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
