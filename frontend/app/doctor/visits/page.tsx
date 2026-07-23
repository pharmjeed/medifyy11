"use client";

/** الصفحة 12 — سجل الزيارات W-202 (القائمة) + W-221 (تفاصيل زيارة للقراءة فقط عبر ?open=). */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import type { GuidanceItem, UploadStatus, VisitRow, VisitState, VisitSummary } from "@/lib/types";
import { Shell } from "@/components/Shell";
import { SpecBar, VisitStateBadge, fmtDateTime, useErrorScreen, useToast, visitStateLabel } from "@/components/ui";

const LIST_GRID = "1.2fr .9fr 1.7fr .8fr .8fr 1.1fr 1.1fr";

const STATE_ORDER: VisitState[] = [
  "draft", "recording", "transcribed", "summarized",
  "in_review", "approved", "uploaded", "upload_failed", "cancelled",
];

/** عناوين الأقسام المعروفة (الأقسام ديناميكية من القالب — fallback بحرف المفتاح). */
const SECTION_TITLES: Record<string, { ar: string; en: string }> = {
  S: { ar: "الذاتي — Subjective", en: "Subjective" },
  O: { ar: "الموضوعي — Objective", en: "Objective" },
  A: { ar: "التقييم — Assessment", en: "Assessment" },
  P: { ar: "الخطة — Plan", en: "Plan" },
  E: { ar: "تثقيف المريض — Patient education", en: "Patient education" },
};

/** زر الإجراء حسب الحالة (نفس قاعدة رئيسة الدكتور). */
function actionFor(row: VisitRow): { label: { ar: string; en: string }; href: string } | null {
  switch (row.state) {
    case "in_review": return { label: { ar: "فتح المراجعة", en: "Open review" }, href: `/doctor/visits/${row.id}/review` };
    case "uploaded": return { label: { ar: "عرض للقراءة", en: "View read-only" }, href: `/doctor/visits?open=${row.id}` };
    case "upload_failed": return { label: { ar: "إعادة المحاولة", en: "Retry" }, href: `/doctor/visits/${row.id}/review` };
    case "draft": return { label: { ar: "استئناف", en: "Resume" }, href: `/doctor/visits/new?resume=${row.id}` };
    case "summarized": return { label: { ar: "بدء المراجعة", en: "Start review" }, href: `/doctor/visits/${row.id}/review` };
    default: return null;
  }
}

function SectionKeyBox({ sectionKey }: { sectionKey: string }) {
  return (
    <span style={{
      width: 30, height: 30, borderRadius: 8, background: "#005a55", color: "#fff",
      display: "inline-flex", alignItems: "center", justifyContent: "center", fontWeight: 800, flexShrink: 0,
    }}>
      <bdi className="ui">{sectionKey}</bdi>
    </span>
  );
}

function GuidanceStatusBadge({ status }: { status: GuidanceItem["status"] }) {
  const { L } = useLang();
  if (status === "accepted") return <span className="badge success">{L("مقبول ✓", "Accepted ✓")}</span>;
  if (status === "modified") return <span className="badge success">{L("مقبول — معدّل", "Accepted — modified")}</span>;
  if (status === "rejected") return <span className="badge danger">{L("مرفوض", "Rejected")}</span>;
  return <span className="badge warn">{L("معلق", "Pending")}</span>;
}

/* ===== W-221 — عرض التفاصيل للقراءة فقط ===== */
function VisitDetail({ visitId, row }: { visitId: string; row: VisitRow | undefined }) {
  const showError = useErrorScreen();
  const { L } = useLang();
  const [summary, setSummary] = useState<VisitSummary | null>(null);
  const [upload, setUpload] = useState<UploadStatus | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [summaryBody, uploadBody] = await Promise.all([
          api<VisitSummary>(`/visits/${visitId}/summary`),
          api<UploadStatus>(`/visits/${visitId}/upload-status`),
        ]);
        setSummary(summaryBody.data);
        setUpload(uploadBody.data);
      } catch (err) {
        showError(err);
      }
    })();
  }, [visitId, showError]);

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <Link href="/doctor/visits" className="btn-secondary h40" style={{ textDecoration: "none" }}>{L("→ رجوع للسجل", "← Back to log")}</Link>
        <h1 style={{ fontSize: 18, fontWeight: 800, margin: 0, flex: 1 }}>{L("تفاصيل زيارة سابقة", "Past visit details")}</h1>
        <span className="badge neutral">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
          {L("قراءة فقط — معتمدة ومرفوعة", "Read-only — approved and uploaded")} (<bdi>MDF-4226</bdi>)
        </span>
      </div>

      {/* بطاقة رأس الزيارة */}
      <div className="card" style={{ marginTop: 14, display: "flex", gap: 20, flexWrap: "wrap", alignItems: "center" }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div style={{ fontSize: 16, fontWeight: 800 }}>{row !== undefined ? row.patient_name : "—"}</div>
          <div style={{ fontSize: 12.5, color: "#5c7096" }}>
            {L("ملف", "MRN")} {row !== undefined ? <bdi>{row.patient_mrn}</bdi> : "—"}
          </div>
        </div>
        <div style={{ fontSize: 14 }}>
          <span style={{ color: "#5c7096" }}>{L("القالب: ", "Template: ")}</span>
          {row !== undefined ? row.template_name : "—"}
        </div>
        <div style={{ fontSize: 14 }}>
          <span style={{ color: "#5c7096" }}>{L("الوقت: ", "Time: ")}</span>
          {row !== undefined ? fmtDateTime(row.created_at) : "—"}
        </div>
      </div>

      {summary === null ? (
        <div className="card" style={{ marginTop: 12, textAlign: "center", color: "#5c7096" }}>{L("جارٍ التحميل…", "Loading…")}</div>
      ) : (
        <>
          {/* بطاقات الأقسام */}
          {summary.sections.slice().sort((a, b) => a.position - b.position).map((section) => {
            const resolved = section.guidance.filter((item) => item.status !== "pending");
            const title = SECTION_TITLES[section.section_key];
            return (
              <div key={section.id} className="card" style={{ marginTop: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <SectionKeyBox sectionKey={section.section_key} />
                  <strong style={{ fontSize: 15 }}>
                    {title !== undefined ? L(title.ar, title.en) : L(`قسم ${section.section_key}`, `Section ${section.section_key}`)}
                  </strong>
                </div>
                <div className="clinical" style={{ marginTop: 8 }}>{section.content_current}</div>
                {resolved.length > 0 ? (
                  <div style={{ borderTop: "1px dashed #c7d1e0", marginTop: 10, paddingTop: 10, display: "flex", gap: 10, flexWrap: "wrap" }}>
                    {resolved.map((item) => (
                      <span key={item.id} style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                        {item.code_system !== null && item.code_value !== null ? (
                          <span className="code-badge">{item.code_system} · {item.code_value}</span>
                        ) : null}
                        <GuidanceStatusBadge status={item.status} />
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}

          {/* سجل الاعتماد — إلحاقي غير قابل للتعديل */}
          {summary.approval !== null ? (
            <div className="card" style={{ marginTop: 12, border: "1px solid #12a594" }}>
              <strong style={{ color: "#12a594", fontSize: 14 }}>{L("سجل الاعتماد — إلحاقي غير قابل للتعديل", "Approval record — append-only, immutable")}</strong>
              <div style={{ fontSize: 14, marginTop: 6 }}>
                {L("اعتمدها:", "Approved by:")} {summary.approval.approved_by} · {fmtDateTime(summary.approval.approved_at)}
              </div>
              <div style={{ fontSize: 12.5, color: "#5c7096", marginTop: 2 }}>
                {L("بصمة الملخص:", "Summary hash:")} <bdi>sha256:{summary.approval.summary_hash.slice(0, 8)}…</bdi>
              </div>
              <div style={{ fontSize: 12.5, color: "#5c7096", marginTop: 2 }}>
                {L("بصمة الرموز:", "Codes hash:")} <bdi>sha256:{summary.approval.codes_hash.slice(0, 8)}…</bdi>
              </div>
            </div>
          ) : null}

          {/* إيصال الرفع */}
          {upload !== null ? (
            <div className="card" style={{ marginTop: 12 }}>
              <strong style={{ fontSize: 14 }}>{L("إيصال الرفع", "Upload receipt")}</strong>
              <div style={{ fontSize: 14, marginTop: 6 }}>
                {L("الحالة:", "Status:")} <bdi>{upload.status}</bdi> · {L("المحاولات:", "Attempts:")} <span className="num">{upload.attempts_count}</span>
              </div>
            </div>
          ) : null}
        </>
      )}
    </>
  );
}

/* ===== W-202 — القائمة ===== */
function VisitsInner() {
  const params = useSearchParams();
  const showError = useErrorScreen();
  const toast = useToast();
  const { L, lang } = useLang();
  const openId = params.get("open");

  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<VisitState | "all">("all");
  const [rows, setRows] = useState<VisitRow[] | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const search = query.trim() === "" ? "" : `&query=${encodeURIComponent(query.trim())}`;
        const body = await api<VisitRow[]>(`/visits?per_page=100${search}`);
        setRows(body.data);
      } catch (err) {
        showError(err);
      }
    })();
  }, [query, showError]);

  const all = useMemo(() => rows ?? [], [rows]);
  const counts = useMemo(() => {
    const map = new Map<VisitState, number>();
    for (const row of all) map.set(row.state, (map.get(row.state) ?? 0) + 1);
    return map;
  }, [all]);
  const filtered = filter === "all" ? all : all.filter((row) => row.state === filter);

  if (openId !== null) {
    return (
      <>
        <SpecBar ids="W-202 · W-221" desc={L("الصفحة 12 — السجل + التفاصيل عرض فرعي للقراءة فقط", "Page 12 — log + read-only detail subview")} />
        <VisitDetail visitId={openId} row={all.find((row) => row.id === openId)} />
      </>
    );
  }

  return (
    <>
      <SpecBar ids="W-202 · W-221" desc={L("الصفحة 12 — السجل + التفاصيل عرض فرعي للقراءة فقط", "Page 12 — log + read-only detail subview")} />
      <h1 className="page-title">{L("سجل الزيارات", "Visit log")}</h1>
      <p className="page-desc">{L("زياراتك أنت فقط", "Your own visits only")} (<bdi>doctor_id = self</bdi>)</p>

      <input
        className="field search"
        placeholder={L("بحث باسم المريض أو رقم الملف…", "Search by patient name or MRN…")}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        aria-label={L("بحث باسم المريض أو رقم الملف", "Search by patient name or MRN")}
      />

      {/* حبوب فلتر الحالة — العدادات من النتيجة غير المفلترة بالحالة */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "12px 0 16px" }}>
        <button className={filter === "all" ? "pill active" : "pill"} onClick={() => setFilter("all")}>
          {L("الكل", "All")} <span className="num">{all.length}</span>
        </button>
        {STATE_ORDER.filter((state) => (counts.get(state) ?? 0) > 0).map((state) => (
          <button key={state} className={filter === state ? "pill active" : "pill"} onClick={() => setFilter(state)}>
            {visitStateLabel(state, lang)} <span className="num">{counts.get(state) ?? 0}</span>
          </button>
        ))}
      </div>

      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: LIST_GRID }}>
          <div>{L("الوقت", "Time")}</div><div>{L("الزيارة", "Visit")}</div><div>{L("المريض", "Patient")}</div><div>{L("الملف", "MRN")}</div><div>{L("العيادة", "Clinic")}</div><div>{L("الحالة", "Status")}</div><div>{L("إجراء", "Action")}</div>
        </div>
        {rows === null ? (
          <div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div>
        ) : filtered.length === 0 ? (
          <div className="grid-empty">{L("لا زيارات مطابقة للبحث", "No visits match your search")}</div>
        ) : (
          filtered.map((row, index) => {
            const action = actionFor(row);
            return (
              <div key={row.id} className={index % 2 === 1 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: LIST_GRID }}>
                <div>{fmtDateTime(row.created_at)}</div>
                <div><bdi>{row.id.slice(0, 8)}</bdi></div>
                <div>{row.patient_name}</div>
                <div><bdi>{row.patient_mrn}</bdi></div>
                <div>{L("الباطنة", "Internal medicine")}</div>
                <div><VisitStateBadge state={row.state} /></div>
                <div>
                  {row.state === "cancelled" ? (
                    <button className="btn-row neutral" onClick={() => toast(L("زيارة ملغاة بقرار الدكتور — لا اعتماد ولا رفع", "Visit cancelled by the doctor — no approval, no upload"))}>
                      {L("ملغاة — عرض", "Cancelled — view")}
                    </button>
                  ) : action !== null ? (
                    <Link href={action.href} className="btn-row" style={{ textDecoration: "none", display: "inline-flex", alignItems: "center" }}>
                      {L(action.label.ar, action.label.en)}
                    </Link>
                  ) : (
                    <span style={{ color: "#5c7096" }}>—</span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      <p style={{ fontSize: 12.5, color: "#5c7096", marginTop: 12 }}>
        {L("آلة الحالات أحادية الاتجاه:", "One-way state machine:")} <bdi>draft → recording → transcribed → summarized → in_review → approved → uploaded | upload_failed</bdi> · {L("الإلغاء حالة نهائية", "Cancellation is a terminal state")} <bdi>cancelled</bdi> {L("متاحة قبل الاعتماد فقط", "available only before approval")}
      </p>
    </>
  );
}

export default function DoctorVisitsPage() {
  const { L } = useLang();
  return (
    <Shell title={L("سجل الزيارات", "Visit log")}>
      <main className="page-wrap">
        <Suspense>
          <VisitsInner />
        </Suspense>
      </main>
    </Shell>
  );
}
