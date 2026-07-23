"use client";

/** مكونات معيارية مشتركة — مطابقة للنموذج التفاعلي (DOC-11 §٣). */

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { SHOW_SPEC_IDS } from "@/lib/api";
import { ApiError } from "@/lib/api";
import { mdfMeta } from "@/lib/errors";
import { useLang } from "@/lib/i18n";
import type { Speaker, VisitState } from "@/lib/types";

/* ===== شارة المواصفة W-XXX — تظهر فقط عند NEXT_PUBLIC_SHOW_SPEC_IDS=true ===== */
export function SpecBadge({ id }: { id: string }) {
  if (!SHOW_SPEC_IDS) return null;
  return <span className="spec-badge">{id}</span>;
}

export function SpecBar({ ids, desc }: { ids: string; desc: string }) {
  const { L } = useLang();
  if (!SHOW_SPEC_IDS) return null;
  return (
    <div className="spec-bar">
      <span>{L("نسخة التخطيط", "Layout version")}</span>
      <span className="spec-badge" style={{ background: "#00c2b8", color: "#0c1a36", border: "none" }}>{ids}</span>
      <span style={{ fontWeight: 400 }}>{desc}</span>
    </div>
  );
}

/* ===== شارات حالة الزيارة (VSTATES حرفياً + الإنجليزية) ===== */
const VSTATES: Record<VisitState, { ar: string; en: string; bg: string; fg: string }> = {
  draft: { ar: "مسودة", en: "Draft", bg: "#f7f9fb", fg: "#5c7096" },
  recording: { ar: "تسجيل", en: "Recording", bg: "#d6f5f2", fg: "#005a55" },
  transcribed: { ar: "مفرّغة", en: "Transcribed", bg: "#d6f5f2", fg: "#005a55" },
  summarized: { ar: "ملخّصة", en: "Summarized", bg: "rgba(42,111,151,.12)", fg: "#3b82c4" },
  in_review: { ar: "قيد المراجعة", en: "In review", bg: "#fdf4e0", fg: "#9c6f00" },
  approved: { ar: "معتمدة", en: "Approved", bg: "#e6f7f4", fg: "#12a594" },
  uploaded: { ar: "مرفوعة ✓", en: "Uploaded ✓", bg: "#e6f7f4", fg: "#12a594" },
  upload_failed: { ar: "فشل الرفع", en: "Upload failed", bg: "#fbeaea", fg: "#d94b4b" },
  cancelled: { ar: "ملغاة", en: "Cancelled", bg: "#f7f9fb", fg: "#5c7096" },
};

export function VisitStateBadge({ state }: { state: VisitState }) {
  const { L } = useLang();
  const meta = VSTATES[state];
  return (
    <span className="badge" style={{ background: meta.bg, color: meta.fg }}>
      {L(meta.ar, meta.en)}
    </span>
  );
}

export function visitStateLabel(state: VisitState, lang?: "ar" | "en"): string {
  const current = lang ?? (typeof document !== "undefined" && document.documentElement.lang === "ar" ? "ar" : "en");
  return current === "ar" ? VSTATES[state].ar : VSTATES[state].en;
}

/* ===== شارة هوية المتحدث — طبيب/مريض مُستنتَجة من محتوى الكلام وسياق المحادثة =====
   الطبيب يحتفظ باللون الفيروزي المألوف؛ المريض بلون أزرق مميّز.
   عند تدنّي الثقة تُعرض الشارة باهتة مع "؟" لأن الإسناد استدلالي لا صوتي. */
const SPEAKERS: Record<Speaker, { ar: string; en: string; bg: string; fg: string; dot: string }> = {
  doctor: { ar: "الطبيب", en: "Doctor", bg: "#d6f5f2", fg: "#005a55", dot: "#00736d" },
  patient: { ar: "المريض", en: "Patient", bg: "rgba(42,111,151,.12)", fg: "#3b82c4", dot: "#3b82c4" },
};

export function SpeakerBadge({ speaker, confidence }: { speaker?: Speaker; confidence?: number }) {
  const { L } = useLang();
  if (speaker === undefined) {
    // مقطع مؤقت (partial) لا يزال يُبثّ — لم يُسنَد بعد
    return <span className="badge" style={{ background: "#eef2f7", color: "#5c7096" }}>{L("كلام", "Speech")}</span>;
  }
  const meta = SPEAKERS[speaker];
  const uncertain = confidence !== undefined && confidence < 0.62;
  return (
    <span
      className="badge"
      style={{ background: meta.bg, color: meta.fg, opacity: uncertain ? 0.72 : 1, display: "inline-flex", alignItems: "center", gap: 5 }}
      title={uncertain ? L("إسناد مبدئي — راجعه في نص المحادثة", "Tentative attribution — review in the transcript") : undefined}
    >
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: meta.dot, display: "inline-block", flex: "0 0 auto" }} />
      {L(meta.ar, meta.en)}{uncertain ? " ؟" : ""}
    </span>
  );
}

/* ===== التوست — رسالة واحدة تختفي بعد 3000ms ===== */
interface ToastContextValue {
  toast: (message: string) => void;
}
const ToastContext = createContext<ToastContextValue>({ toast: () => undefined });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const toast = useCallback((text: string) => {
    if (timer.current) clearTimeout(timer.current);
    setMessage(text);
    timer.current = setTimeout(() => setMessage(null), 3000);
  }, []);
  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      {message !== null ? <div className="toast" role="status">{message}</div> : null}
    </ToastContext.Provider>
  );
}

export function useToast(): (message: string) => void {
  return useContext(ToastContext).toast;
}

/* ===== شاشة الخطأ العامة W-004 — رمز MDF + إجراء مقترح ===== */
interface ErrorScreenContextValue {
  showError: (error: unknown) => void;
}
const ErrorScreenContext = createContext<ErrorScreenContextValue>({ showError: () => undefined });

export function ErrorScreenProvider({ children }: { children: ReactNode }) {
  const { lang, L } = useLang();
  const [current, setCurrent] = useState<{ code: string; messageAr: string; action: string } | null>(null);
  const showError = useCallback((error: unknown) => {
    if (error instanceof ApiError) {
      const meta = mdfMeta(error.code, lang);
      setCurrent({ code: error.code, messageAr: error.text(lang) || meta.message_ar, action: meta.action });
    } else {
      const meta = mdfMeta("MDF-5001", lang);
      setCurrent({ code: "MDF-5001", messageAr: meta.message_ar, action: meta.action });
    }
  }, [lang]);
  return (
    <ErrorScreenContext.Provider value={{ showError }}>
      {children}
      {current !== null ? (
        <div
          style={{ position: "fixed", inset: 0, zIndex: 70, background: "rgba(12,26,54,.55)", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}
          onClick={() => setCurrent(null)}
        >
          <div
            style={{ width: "min(470px,94vw)", background: "#fff", borderRadius: 12, padding: 28, position: "relative", animation: "mIn .18s ease", textAlign: "center" }}
            onClick={(event) => event.stopPropagation()}
          >
            <div style={{ position: "absolute", top: 12, insetInlineStart: 12 }}><SpecBadge id="W-004" /></div>
            <div style={{ width: 56, height: 56, borderRadius: 999, background: "#fbeaea", display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#d94b4b" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4" /><path d="M12 17h.01" />
              </svg>
            </div>
            <div style={{ marginTop: 10 }}>
              <bdi style={{ fontSize: 22, fontWeight: 700, color: "#d94b4b" }}>{current.code}</bdi>
            </div>
            <div style={{ fontSize: 18, fontWeight: 700, color: "#005a55", marginTop: 6 }}>{L("حدث خطأ", "An error occurred")}</div>
            <p style={{ fontSize: 14, color: "#5c7096", margin: "8px 0 4px" }}>{current.messageAr}</p>
            <p style={{ fontSize: 12.5, color: "#5c7096", margin: "0 0 16px" }}>{current.action}</p>
            <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
              <button className="btn" onClick={() => { setCurrent(null); window.location.reload(); }}>{L("إعادة المحاولة", "Retry")}</button>
              <button className="btn-secondary" onClick={() => setCurrent(null)}>{L("إغلاق", "Close")}</button>
            </div>
            <p style={{ fontSize: 12.5, color: "#5c7096", marginTop: 14, marginBottom: 0 }}>
              {L("كل رمز", "Every")} <bdi>MDF</bdi> {L("برسالتين عربية/إنجليزية — النظام حصري من", "code is bilingual (Arabic/English) — the registry is exclusive to")} <bdi>DOC-13</bdi>.
            </p>
          </div>
        </div>
      ) : null}
    </ErrorScreenContext.Provider>
  );
}

export function useErrorScreen(): (error: unknown) => void {
  return useContext(ErrorScreenContext).showError;
}

/* ===== المودال المركزي ===== */
export function Modal({
  title, spec, onClose, children, wide,
}: {
  title: string;
  spec?: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const { L } = useLang();
  useEffect(() => {
    const handler = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);
  return (
    <>
      <div className="modal-overlay" onClick={onClose} />
      <div className={wide === true ? "modal wide" : "modal"} role="dialog" aria-modal="true">
        <div className="modal-head">
          <div className="modal-title">{title}</div>
          {spec !== undefined ? <SpecBadge id={spec} /> : null}
          <button className="modal-close" aria-label={L("إغلاق", "Close")} onClick={onClose}>✕</button>
        </div>
        {children}
      </div>
    </>
  );
}

/* ===== حقل بنموذج تسمية ===== */
export function Field({
  label, ltr, ...props
}: { label: string; ltr?: boolean } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <>
      <label className="field-label">{label}</label>
      <input className={ltr === true ? "field mono" : "field"} dir={ltr === true ? "ltr" : undefined} {...props} />
    </>
  );
}

/* ===== التبويبات ===== */
export function Tabs<T extends string>({
  tabs, active, onChange,
}: { tabs: { key: T; label: ReactNode }[]; active: T; onChange: (key: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          role="tab"
          aria-selected={tab.key === active}
          className={tab.key === active ? "tab active" : "tab"}
          onClick={() => onChange(tab.key)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

/* ===== تنسيقات وقت/تاريخ موجزة (بلغة الواجهة الحالية) ===== */
export function fmtDateTime(iso: string): string {
  const arabic = typeof document !== "undefined" && document.documentElement.lang === "ar";
  const date = new Date(iso);
  const today = new Date();
  const time = date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const sameDay = date.toDateString() === today.toDateString();
  if (sameDay) return `${arabic ? "اليوم" : "Today"} ${time}`;
  const yesterday = new Date(today.getTime() - 86400000);
  if (date.toDateString() === yesterday.toDateString()) return `${arabic ? "أمس" : "Yesterday"} ${time}`;
  return `${date.toISOString().slice(0, 10)} ${time}`;
}

export function initials(name: string): string {
  const clean = name.replace(/^(د\.|أ\.)\s*/, "").trim();
  return clean.slice(0, 2);
}
