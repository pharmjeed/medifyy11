"use client";

/** الصفحة 9 — التحليلات W-108/W-109: تبويبا الاستخدام والجودة (FR-401/402) — تجميعات فقط (DOC-06). */

import { useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { SpecBadge, SpecBar, Tabs, VisitStateBadge, useToast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { QualityDashboard, UsageDashboard, VisitState } from "@/lib/types";

function apiErrorText(err: unknown): string {
  return err instanceof ApiError ? `${err.messageAr} (${err.code})` : "تعذر الاتصال بالخادم";
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
  const [data, setData] = useState<UsageDashboard | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const body = await api<UsageDashboard>("/dashboards/usage");
      setData(body.data);
    } catch (err) {
      toast(apiErrorText(err));
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { void load(); }, [load]);

  if (loading) return <div className="grid-empty">جارٍ التحميل…</div>;
  if (data === null) return <div className="grid-empty">تعذر تحميل لوحة الاستخدام</div>;

  const stateEntries = STATES
    .map((state) => ({ state, count: data.by_state[state] }))
    .filter((entry): entry is { state: VisitState; count: number } => entry.count !== undefined);

  return (
    <>
      <div className="stat-grid">
        <div className="card">
          <div className="stat-label">إجمالي الزيارات</div>
          <div className="stat-value num">{data.total_visits}</div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <div className="stat-label">توزيع الحالات</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center", marginTop: 6 }}>
            {stateEntries.length === 0 ? (
              <span style={{ fontSize: 14, color: "#5B7280" }}>لا زيارات بعد</span>
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
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 10px" }}>زيارات لكل دكتور</h2>
          <div className="grid-table">
            <div className="grid-head" style={{ gridTemplateColumns: COUNT_COLS }}>
              <div>الدكتور</div><div>الزيارات</div>
            </div>
            {data.by_doctor.length === 0 ? (
              <div className="grid-empty">لا بيانات بعد</div>
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
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 10px" }}>لكل عيادة</h2>
          <div className="grid-table">
            <div className="grid-head" style={{ gridTemplateColumns: COUNT_COLS }}>
              <div>العيادة</div><div>الزيارات</div>
            </div>
            {data.by_clinic.length === 0 ? (
              <div className="grid-empty">لا بيانات بعد</div>
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
const GUIDANCE_ROWS: { key: "pending" | "accepted" | "rejected" | "modified"; label: string }[] = [
  { key: "pending", label: "معلق" },
  { key: "accepted", label: "مقبول" },
  { key: "rejected", label: "مرفوض" },
  { key: "modified", label: "معدّل" },
];

const CHANNEL_ROWS: { key: "typing" | "voice" | "ai_chat"; label: string }[] = [
  { key: "typing", label: "كتابة" },
  { key: "voice", label: "صوت" },
  { key: "ai_chat", label: "محادثة AI" },
];

function QualityTab() {
  const toast = useToast();
  const [data, setData] = useState<QualityDashboard | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const body = await api<QualityDashboard>("/dashboards/quality");
      setData(body.data);
    } catch (err) {
      toast(apiErrorText(err));
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { void load(); }, [load]);

  if (loading) return <div className="grid-empty">جارٍ التحميل…</div>;
  if (data === null) return <div className="grid-empty">تعذر تحميل لوحة الجودة</div>;

  return (
    <>
      <div className="stat-grid">
        <div className="card">
          <div className="stat-label">نسبة الاعتماد دون تعديل</div>
          <div className="stat-value num">{pct(data.approved_without_edit_pct)}</div>
          <div style={{ fontSize: 12.5, color: "#5B7280" }}>
            من <span className="num">{data.summaries_total}</span> ملخصاً (<bdi>approved_without_edit_pct</bdi>)
          </div>
        </div>
        <div className="card">
          <div className="stat-label">نسبة قبول الإرشادات</div>
          <div className="stat-value num">{pct(data.guidance_accept_rate_pct)}</div>
          <div style={{ fontSize: 12.5, color: "#5B7280" }}>
            المقبول + المعدّل من المحسوم (<bdi>guidance_accept_rate_pct</bdi>)
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 14, marginTop: 14 }}>
        <div>
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 10px" }}>الإرشادات حسب الحالة</h2>
          <div className="grid-table">
            <div className="grid-head" style={{ gridTemplateColumns: COUNT_COLS }}>
              <div>الحالة</div><div>العدد</div>
            </div>
            {GUIDANCE_ROWS.map((row, i) => (
              <div key={row.key} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: COUNT_COLS }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {row.label} <span className="tech-badge">{row.key}</span>
                </div>
                <div className="num" style={{ fontWeight: 700 }}>{data.guidance_by_status[row.key] ?? 0}</div>
              </div>
            ))}
          </div>
        </div>
        <div>
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 10px" }}>قنوات التحرير</h2>
          <div className="grid-table">
            <div className="grid-head" style={{ gridTemplateColumns: COUNT_COLS }}>
              <div>القناة</div><div>العدد</div>
            </div>
            {CHANNEL_ROWS.map((row, i) => (
              <div key={row.key} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: COUNT_COLS }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {row.label} <span className="tech-badge">{row.key}</span>
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
  const [tab, setTab] = useState<"usage" | "quality">("usage");
  return (
    <>
      <SpecBar ids="W-108 · W-109" desc="الصفحة 9 — تبويبا الاستخدام والجودة (FR-401/402)" />
      <Tabs
        tabs={[
          { key: "usage", label: <>الاستخدام <SpecBadge id="W-108" /></> },
          { key: "quality", label: <>الجودة <SpecBadge id="W-109" /></> },
        ]}
        active={tab}
        onChange={setTab}
      />
      {tab === "usage" ? <UsageTab /> : <QualityTab />}
      <p style={{ fontSize: 12.5, color: "#5B7280", margin: "18px 0 0" }}>
        تجميعات فقط — لا محتوى سريرياً في لوحات الأدمن (DOC-06)
      </p>
    </>
  );
}

export default function AnalyticsPage() {
  return (
    <Shell title="التحليلات">
      <main className="page-wrap">
        <AnalyticsInner />
      </main>
    </Shell>
  );
}
