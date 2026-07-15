"use client";

/** الصفحة 9 — التحليلات W-108/W-109: تبويبا الاستخدام والجودة (FR-401/402) — تجميعات فقط (DOC-06). */

import { useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { SpecBadge, SpecBar, Tabs, VisitStateBadge, useToast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import type { Lang } from "@/lib/i18n";
import type { QualityDashboard, UsageDashboard, VisitState } from "@/lib/types";

function apiErrorText(err: unknown, lang: Lang, L: (ar: string, en: string) => string): string {
  return err instanceof ApiError ? `${err.text(lang)} (${err.code})` : L("تعذر الاتصال بالخادم", "Could not reach the server");
}

const STATES: VisitState[] = [
  "draft", "recording", "transcribed", "summarized",
  "in_review", "approved", "uploaded", "upload_failed", "cancelled",
];

const COUNT_COLS = "2fr 1fr";

function pct(value: number | null): string {
  return value === null ? "—" : `${value}%`;
}

/* ===== تبويب «الاستخدام» W-108 ===== */
function UsageTab() {
  const toast = useToast();
  const { L, lang } = useLang();
  const [data, setData] = useState<UsageDashboard | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const body = await api<UsageDashboard>("/dashboards/usage");
      setData(body.data);
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setLoading(false);
    }
  }, [toast, lang, L]);

  useEffect(() => { void load(); }, [load]);

  if (loading) return <div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div>;
  if (data === null) return <div className="grid-empty">{L("تعذر تحميل لوحة الاستخدام", "Could not load the usage dashboard")}</div>;

  const stateEntries = STATES
    .map((state) => ({ state, count: data.by_state[state] }))
    .filter((entry): entry is { state: VisitState; count: number } => entry.count !== undefined);

  return (
    <>
      <div className="stat-grid">
        <div className="card">
          <div className="stat-label">{L("إجمالي الزيارات", "Total visits")}</div>
          <div className="stat-value num">{data.total_visits}</div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <div className="stat-label">{L("توزيع الحالات", "State distribution")}</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center", marginTop: 6 }}>
            {stateEntries.length === 0 ? (
              <span style={{ fontSize: 14, color: "#5B7280" }}>{L("لا زيارات بعد", "No visits yet")}</span>
            ) : (
              stateEntries.map(({ state, count }) => (
                <span key={state} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  <VisitStateBadge state={state} />
                  <span className="num" style={{ fontWeight: 700 }}>{count}</span>
                </span>
              ))
            )}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 14, marginTop: 14 }}>
        <div>
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 10px" }}>{L("زيارات لكل دكتور", "Visits per doctor")}</h2>
          <div className="grid-table">
            <div className="grid-head" style={{ gridTemplateColumns: COUNT_COLS }}>
              <div>{L("الدكتور", "Doctor")}</div><div>{L("الزيارات", "Visits")}</div>
            </div>
            {data.by_doctor.length === 0 ? (
              <div className="grid-empty">{L("لا بيانات بعد", "No data yet")}</div>
            ) : (
              data.by_doctor.map((row, i) => (
                <div key={row.doctor} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: COUNT_COLS }}>
                  <div>{row.doctor}</div>
                  <div className="num" style={{ fontWeight: 700 }}>{row.visits}</div>
                </div>
              ))
            )}
          </div>
        </div>
        <div>
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 10px" }}>{L("لكل عيادة", "Per clinic")}</h2>
          <div className="grid-table">
            <div className="grid-head" style={{ gridTemplateColumns: COUNT_COLS }}>
              <div>{L("العيادة", "Clinic")}</div><div>{L("الزيارات", "Visits")}</div>
            </div>
            {data.by_clinic.length === 0 ? (
              <div className="grid-empty">{L("لا بيانات بعد", "No data yet")}</div>
            ) : (
              data.by_clinic.map((row, i) => (
                <div key={row.clinic} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: COUNT_COLS }}>
                  <div>{row.clinic}</div>
                  <div className="num" style={{ fontWeight: 700 }}>{row.visits}</div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </>
  );
}

/* ===== تبويب «الجودة» W-109 ===== */
const GUIDANCE_ROWS: { key: "pending" | "accepted" | "rejected" | "modified"; label: { ar: string; en: string } }[] = [
  { key: "pending", label: { ar: "معلق", en: "Pending" } },
  { key: "accepted", label: { ar: "مقبول", en: "Accepted" } },
  { key: "rejected", label: { ar: "مرفوض", en: "Rejected" } },
  { key: "modified", label: { ar: "معدّل", en: "Modified" } },
];

const CHANNEL_ROWS: { key: "typing" | "voice" | "ai_chat"; label: { ar: string; en: string } }[] = [
  { key: "typing", label: { ar: "كتابة", en: "Typing" } },
  { key: "voice", label: { ar: "صوت", en: "Voice" } },
  { key: "ai_chat", label: { ar: "محادثة AI", en: "AI chat" } },
];

function QualityTab() {
  const toast = useToast();
  const { L, lang } = useLang();
  const [data, setData] = useState<QualityDashboard | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const body = await api<QualityDashboard>("/dashboards/quality");
      setData(body.data);
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setLoading(false);
    }
  }, [toast, lang, L]);

  useEffect(() => { void load(); }, [load]);

  if (loading) return <div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div>;
  if (data === null) return <div className="grid-empty">{L("تعذر تحميل لوحة الجودة", "Could not load the quality dashboard")}</div>;

  return (
    <>
      <div className="stat-grid">
        <div className="card">
          <div className="stat-label">{L("نسبة الاعتماد دون تعديل", "Approved without edits")}</div>
          <div className="stat-value num">{pct(data.approved_without_edit_pct)}</div>
          <div style={{ fontSize: 12.5, color: "#5B7280" }}>
            {L("من", "Of")} <span className="num">{data.summaries_total}</span> {L("ملخصاً", "summaries")} (<bdi>approved_without_edit_pct</bdi>)
          </div>
        </div>
        <div className="card">
          <div className="stat-label">{L("نسبة قبول الإرشادات", "Guidance acceptance rate")}</div>
          <div className="stat-value num">{pct(data.guidance_accept_rate_pct)}</div>
          <div style={{ fontSize: 12.5, color: "#5B7280" }}>
            {L("المقبول + المعدّل من المحسوم", "Accepted + modified out of resolved")} (<bdi>guidance_accept_rate_pct</bdi>)
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 14, marginTop: 14 }}>
        <div>
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 10px" }}>{L("الإرشادات حسب الحالة", "Guidance by status")}</h2>
          <div className="grid-table">
            <div className="grid-head" style={{ gridTemplateColumns: COUNT_COLS }}>
              <div>{L("الحالة", "Status")}</div><div>{L("العدد", "Count")}</div>
            </div>
            {GUIDANCE_ROWS.map((row, i) => (
              <div key={row.key} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: COUNT_COLS }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {L(row.label.ar, row.label.en)} <span className="tech-badge">{row.key}</span>
                </div>
                <div className="num" style={{ fontWeight: 700 }}>{data.guidance_by_status[row.key] ?? 0}</div>
              </div>
            ))}
          </div>
        </div>
        <div>
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 10px" }}>{L("قنوات التحرير", "Editing channels")}</h2>
          <div className="grid-table">
            <div className="grid-head" style={{ gridTemplateColumns: COUNT_COLS }}>
              <div>{L("القناة", "Channel")}</div><div>{L("العدد", "Count")}</div>
            </div>
            {CHANNEL_ROWS.map((row, i) => (
              <div key={row.key} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: COUNT_COLS }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {L(row.label.ar, row.label.en)} <span className="tech-badge">{row.key}</span>
                </div>
                <div className="num" style={{ fontWeight: 700 }}>{data.edits_by_channel[row.key] ?? 0}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

/* ===== الصفحة ===== */
function AnalyticsInner() {
  const { L } = useLang();
  const [tab, setTab] = useState<"usage" | "quality">("usage");
  return (
    <>
      <SpecBar ids="W-108 · W-109" desc={L("الصفحة 9 — تبويبا الاستخدام والجودة (FR-401/402)", "Page 9 — usage and quality tabs (FR-401/402)")} />
      <Tabs
        tabs={[
          { key: "usage", label: <>{L("الاستخدام", "Usage")} <SpecBadge id="W-108" /></> },
          { key: "quality", label: <>{L("الجودة", "Quality")} <SpecBadge id="W-109" /></> },
        ]}
        active={tab}
        onChange={setTab}
      />
      {tab === "usage" ? <UsageTab /> : <QualityTab />}
      <p style={{ fontSize: 12.5, color: "#5B7280", margin: "18px 0 0" }}>
        {L("تجميعات فقط — لا محتوى سريرياً في لوحات الأدمن (DOC-06)", "Aggregates only — no clinical content in admin dashboards (DOC-06)")}
      </p>
    </>
  );
}

export default function AnalyticsPage() {
  const { L } = useLang();
  return (
    <Shell title={L("التحليلات", "Analytics")}>
      <main className="page-wrap">
        <AnalyticsInner />
      </main>
    </Shell>
  );
}
