"use client";

/** الصفحة 4 — لوحة الأدمن W-101 + بانر التعليق W-207 + نافذة الرفع الفاشل W-209 (FR-103). */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { Modal, SpecBadge, SpecBar, fmtDateTime, useErrorScreen, useToast, visitStateLabel } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import type {
  AuditRow, FailedUploadRow, IntegrationInfo, Me, SubscriptionInfo, UsageDashboard, VisitState,
} from "@/lib/types";

const ALL_STATES: VisitState[] = [
  "draft", "recording", "transcribed", "summarized", "in_review", "approved", "uploaded", "upload_failed", "cancelled",
];

const FACILITY_STATUS: Record<Me["facility_status"], { ar: string; en: string }> = {
  active: { ar: "الحالة: نشطة", en: "Status: active" },
  suspended: { ar: "الحالة: تعليق جزئي — فاتورة متأخرة", en: "Status: partially suspended — overdue invoice" },
  archived: { ar: "الحالة: مؤرشفة", en: "Status: archived" },
};

const FAILED_COLS = "40px 1fr 1.3fr .7fr 1.5fr 1fr";
const AUDIT_COLS = "1.1fr 1.2fr 1.6fr 1.1fr";

function AdminInner() {
  const toast = useToast();
  const showError = useErrorScreen();
  const { L, lang } = useLang();

  const [me, setMe] = useState<Me | null>(null);
  const [sub, setSub] = useState<SubscriptionInfo | null>(null);
  const [usage, setUsage] = useState<UsageDashboard | null>(null);
  const [integration, setIntegration] = useState<IntegrationInfo | null>(null);
  const [failed, setFailed] = useState<FailedUploadRow[]>([]);
  const [failedTotal, setFailedTotal] = useState(0);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [loading, setLoading] = useState(true);

  const [failModal, setFailModal] = useState(false);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [retrying, setRetrying] = useState(false);

  const load = useCallback(async () => {
    try {
      const [meB, subB, usageB, intB, failB, auditB] = await Promise.all([
        api<Me>("/me"),
        api<SubscriptionInfo>("/subscription"),
        api<UsageDashboard>("/dashboards/usage"),
        api<IntegrationInfo>("/settings/integration"),
        api<FailedUploadRow[]>("/uploads/failed?per_page=25"),
        api<AuditRow[]>("/audit-logs?per_page=5"),
      ]);
      setMe(meB.data);
      setSub(subB.data);
      setUsage(usageB.data);
      setIntegration(intB.data);
      setFailed(failB.data);
      setFailedTotal(failB.meta.total ?? failB.data.length);
      setAudit(auditB.data);
    } catch (err) {
      showError(err);
    } finally {
      setLoading(false);
    }
  }, [showError]);

  useEffect(() => { void load(); }, [load]);

  const selectedIds = failed.filter((row) => selected[row.job_id] === true).map((row) => row.job_id);
  const allSelected = failed.length > 0 && failed.every((row) => selected[row.job_id] === true);

  const retrySelected = async () => {
    if (selectedIds.length === 0) {
      toast(L("حدّد صفاً واحداً على الأقل لإعادة المحاولة", "Select at least one row to retry"));
      return;
    }
    setRetrying(true);
    try {
      const body = await api<{ results: { job_id: string; ok: boolean; status?: string }[] }>(
        "/uploads/retry",
        { method: "POST", body: { job_ids: selectedIds } },
      );
      const okCount = body.data.results.filter((result) => result.ok).length;
      toast(L(`أُعيدت المحاولة — نجح ${okCount} من ${body.data.results.length} وسُجّلت في التدقيق (upload.retry)`,
              `Retry submitted — ${okCount} of ${body.data.results.length} succeeded, audit-logged (upload.retry)`));
      setSelected({});
      await load();
    } catch (err) {
      if (err instanceof ApiError) toast(`${err.text(lang)} (${err.code})`);
      else toast(L("تعذر الاتصال بالخادم", "Could not reach the server"));
    } finally {
      setRetrying(false);
    }
  };

  const intStatus = integration === null || integration.last_test_at === null
    ? { color: "#5c7096", label: L("غير مكوّن", "Not configured") }
    : integration.last_test_ok === true
      ? { color: "#12a594", label: L("متصل", "Connected") }
      : { color: "#d94b4b", label: L("فشل آخر اختبار", "Last test failed") };

  const seatsPct = sub !== null && sub.seats_total > 0
    ? Math.round((sub.seats_used / sub.seats_total) * 100)
    : 0;

  return (
    <main className="page-wrap">
      <SpecBar ids="W-101 · W-207 · W-209" desc={L("الصفحة 4 — لوحة الأدمن الرئيسة (FR-103)", "Page 4 — main admin dashboard (FR-103)")} />

      {loading ? (
        <div className="card"><div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div></div>
      ) : (
        <>
          {/* الترويسة */}
          {me !== null ? (
            <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
              <div style={{ flex: 1, minWidth: 220 }}>
                <h1 className="page-title" style={{ margin: 0 }}>{me.facility_name}</h1>
                <p className="page-desc" style={{ margin: 0 }}>{L(FACILITY_STATUS[me.facility_status].ar, FACILITY_STATUS[me.facility_status].en)}</p>
              </div>
              <Link href="/admin/doctors" className="btn" style={{ textDecoration: "none" }}>{L("إدارة الدكاترة", "Manage doctors")}</Link>
            </div>
          ) : null}

          {/* بانر التعليق W-207 */}
          {me !== null && me.facility_status === "suspended" ? (
            <div className="card" style={{ border: "2px solid #9c6f00", marginBottom: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <SpecBadge id="W-207" />
                <bdi style={{ color: "#9c6f00", fontWeight: 700, fontSize: 16 }}>MDF-4013</bdi>
                <strong style={{ color: "#9c6f00", fontSize: 16 }}>{L("إنشاء الزيارات موقوف مؤقتاً", "Visit creation is temporarily suspended")}</strong>
              </div>
              <p style={{ fontSize: 14, margin: "8px 0 12px" }}>
                {L("منشأتك عليها فاتورة متأخرة — المراجعة والاعتماد للزيارات القائمة متاحان، ويبقى إنشاء الزيارات موقوفاً حتى السداد.",
                   "Your facility has an overdue invoice — review and approval of existing visits remain available, and visit creation stays suspended until payment.")}
              </p>
              <Link href="/admin/subscription" className="btn" style={{ textDecoration: "none", background: "#9c6f00" }}>
                {L("سداد الفواتير", "Pay invoices")}
              </Link>
            </div>
          ) : null}

          {/* شبكة البطاقات الإحصائية W-101 */}
          <div className="stat-grid">
            {sub !== null ? (
              <div className="card">
                <div style={{ display: "flex", alignItems: "center" }}>
                  <span className="stat-label" style={{ flex: 1, marginBottom: 0 }}>{L("المقاعد", "Seats")}</span>
                  <Link href="/admin/subscription" className="btn-ghost">{L("إدارة", "Manage")}</Link>
                </div>
                <div className="stat-value">
                  <span className="num">{sub.seats_used}</span> {L("من", "of")} <span className="num">{sub.seats_total}</span>
                </div>
                <div style={{ height: 8, background: "#d6f5f2", borderRadius: 999, margin: "8px 0" }}>
                  <div style={{ height: 8, width: `${seatsPct}%`, background: "#00736d", borderRadius: 999 }} />
                </div>
                <div style={{ fontSize: 12.5, color: "#5c7096" }}>
                  {L("متاح الآن:", "Available now:")} <span className="num">{sub.seats_available}</span> — {L("كل دكتور نشط يستهلك مقعداً", "each active doctor consumes a seat")}
                </div>
              </div>
            ) : null}

            {integration !== null ? (
              <div className="card">
                <div style={{ display: "flex", alignItems: "center" }}>
                  <span className="stat-label" style={{ flex: 1, marginBottom: 0 }}>{L("الربط مع نظام المستشفى", "Hospital system integration")}</span>
                  <Link href="/admin/settings" className="btn-ghost">{L("الإعدادات", "Settings")}</Link>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "8px 0 6px" }}>
                  <span style={{ width: 10, height: 10, borderRadius: 999, background: intStatus.color, flexShrink: 0 }} />
                  <strong style={{ color: intStatus.color, fontSize: 16 }}>{intStatus.label}</strong>
                </div>
                <div style={{ fontSize: 12.5, color: "#5c7096" }}>
                  {integration.last_test_at === null
                    ? L("لم يُجرَ أي اختبار بعد", "No test has been run yet")
                    : `${L("آخر اختبار:", "Last test:")} ${fmtDateTime(integration.last_test_at)} — ${integration.last_test_ok === true ? L("ناجح", "passed") : L("فاشل", "failed")}`}
                </div>
                <div style={{ fontSize: 12.5, color: "#5c7096" }}>
                  {L("الوضع:", "Mode:")} <bdi>{integration.mode}</bdi> · {L("الرفع بصيغة", "Upload format")} <bdi>FHIR/NPHIES</bdi>
                </div>
              </div>
            ) : null}

            {usage !== null ? (
              <div className="card">
                <div style={{ display: "flex", alignItems: "center" }}>
                  <span className="stat-label" style={{ flex: 1, marginBottom: 0 }}>{L("إجمالي الزيارات", "Total visits")}</span>
                  <Link href="/admin/analytics" className="btn-ghost">{L("التحليلات", "Analytics")}</Link>
                </div>
                <div className="stat-value"><span className="num">{usage.total_visits}</span></div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                  {ALL_STATES.map((state) => {
                    const count = usage.by_state[state];
                    if (count === undefined || count === 0) return null;
                    return (
                      <span key={state} className="badge neutral">
                        {visitStateLabel(state, lang)} <span className="num">{count}</span>
                      </span>
                    );
                  })}
                </div>
              </div>
            ) : null}

            <div className="card">
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className="stat-label" style={{ flex: 1, marginBottom: 0 }}>{L("الرفع الفاشل", "Failed uploads")}</span>
                <SpecBadge id="W-209" />
              </div>
              <div className="stat-value" style={failedTotal > 0 ? { color: "#d94b4b" } : undefined}>
                <span className="num">{failedTotal}</span>
              </div>
              <div style={{ margin: "8px 0" }}>
                <button
                  className={failedTotal > 0 ? "btn-danger-outline" : "btn-neutral"}
                  style={{ height: 36, padding: "0 16px", fontSize: 12.5 }}
                  onClick={() => setFailModal(true)}
                >
                  {L("عرض القائمة", "View list")}
                </button>
              </div>
              <div style={{ fontSize: 12.5, color: "#5c7096" }}>{L("عدادات فقط — لا محتوى سريرياً للأدمن (DOC-06)", "Counters only — no clinical content for the admin (DOC-06)")}</div>
            </div>
          </div>

          {/* آخر النشاط */}
          <div style={{ display: "flex", alignItems: "center", margin: "22px 0 10px" }}>
            <h2 style={{ fontSize: 16, fontWeight: 700, margin: 0, flex: 1 }}>{L("آخر النشاط", "Recent activity")}</h2>
            <Link href="/admin/audit" className="btn-ghost">{L("سجل التدقيق الكامل", "Full audit log")}</Link>
          </div>
          <div className="grid-table">
            <div className="grid-head" style={{ gridTemplateColumns: AUDIT_COLS }}>
              <div>{L("الوقت", "Time")}</div><div>{L("المنفّذ", "Actor")}</div><div>{L("العملية", "Action")}</div><div>{L("الكيان", "Entity")}</div>
            </div>
            {audit.length === 0 ? (
              <div className="grid-empty">{L("لا نشاط بعد — سيظهر هنا كل إجراء إداري واعتماد ورفع", "No activity yet — every admin action, approval, and upload will appear here")}</div>
            ) : (
              audit.map((row, index) => (
                <div key={row.id} className={index % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: AUDIT_COLS }}>
                  <div style={{ fontSize: 12.5 }}>{fmtDateTime(row.at)}</div>
                  <div>{row.actor}</div>
                  <div><span className="tech-badge">{row.action}</span></div>
                  <div><bdi style={{ fontSize: 12.5 }}>{row.entity_id !== null ? `${row.entity}` : row.entity}</bdi></div>
                </div>
              ))
            )}
          </div>
        </>
      )}

      {/* نافذة الرفع الفاشل W-209 */}
      {failModal ? (
        <Modal title={L("الرفع الفاشل — إعادة المحاولة", "Failed uploads — retry")} spec="W-209" wide onClose={() => setFailModal(false)}>
          <p style={{ fontSize: 12.5, color: "#5c7096", margin: "0 0 12px" }}>
            {L("تُعاد المحاولة تلقائياً عند عودة اتصال الربط — هذه القائمة للتدخل اليدوي · بيانات وصفية فقط، لا محتوى سريرياً (DOC-06) · الاعتماد محفوظ ولا يتكرر (FR-803)",
               "Retries run automatically once the integration connection is restored — this list is for manual intervention · metadata only, no clinical content (DOC-06) · approval is preserved and never repeated (FR-803)")}
          </p>
          <div className="grid-table">
            <div className="grid-head" style={{ gridTemplateColumns: FAILED_COLS }}>
              <div style={{ display: "flex", alignItems: "center" }}>
                <input
                  type="checkbox"
                  aria-label={L("تحديد الكل", "Select all")}
                  checked={allSelected}
                  style={{ width: 16, height: 16, accentColor: "#00736d", cursor: "pointer" }}
                  onChange={() => {
                    if (allSelected) { setSelected({}); return; }
                    const next: Record<string, boolean> = {};
                    for (const row of failed) next[row.job_id] = true;
                    setSelected(next);
                  }}
                />
              </div>
              <div>{L("الزيارة", "Visit")}</div><div>{L("الدكتور", "Doctor")}</div><div>{L("المحاولات", "Attempts")}</div><div>{L("الخطأ", "Error")}</div><div>{L("الوقت", "Time")}</div>
            </div>
            {failed.length === 0 ? (
              <div className="grid-empty" style={{ color: "#12a594", fontWeight: 700 }}>{L("لا زيارات فاشلة — كل الرفع مؤكد ✓", "No failed visits — all uploads confirmed ✓")}</div>
            ) : (
              failed.map((row, index) => (
                <div key={row.job_id} className={index % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: FAILED_COLS }}>
                  <div style={{ display: "flex", alignItems: "center" }}>
                    <input
                      type="checkbox"
                      aria-label={L(`تحديد الزيارة ${row.visit_id.slice(0, 8)}`, `Select visit ${row.visit_id.slice(0, 8)}`)}
                      checked={selected[row.job_id] === true}
                      style={{ width: 16, height: 16, accentColor: "#00736d", cursor: "pointer" }}
                      onChange={() => setSelected((prev) => ({ ...prev, [row.job_id]: !(prev[row.job_id] ?? false) }))}
                    />
                  </div>
                  <div><bdi style={{ fontSize: 12.5 }}>{row.visit_id.slice(0, 8)}</bdi></div>
                  <div>{row.doctor}</div>
                  <div><span className="num">{row.attempts_count}</span></div>
                  <div><bdi style={{ color: "#d94b4b", fontSize: 12.5 }}>{row.error_code ?? "—"}</bdi></div>
                  <div style={{ fontSize: 12.5 }}>{fmtDateTime(row.failed_at)}</div>
                </div>
              ))
            )}
          </div>
          {failed.length > 0 ? (
            <div className="modal-actions" style={{ alignItems: "center" }}>
              <button className="btn-danger" onClick={() => void retrySelected()} disabled={retrying}>
                {retrying ? <><span className="spinner" /> {L("يعيد المحاولة…", "Retrying…")}</> : <>{L("إعادة المحاولة للمحدد", "Retry selected")} (<span className="num">{selectedIds.length}</span>)</>}
              </button>
              <span style={{ fontSize: 12.5, color: "#5c7096" }}>{L("كل إعادة تسجَّل في سجل التدقيق (upload.retry)", "Every retry is recorded in the audit log (upload.retry)")}</span>
            </div>
          ) : null}
        </Modal>
      ) : null}
    </main>
  );
}

export default function AdminPage() {
  const { L } = useLang();
  return (
    <Shell title={L("لوحة الأدمن", "Admin dashboard")}>
      <AdminInner />
    </Shell>
  );
}
