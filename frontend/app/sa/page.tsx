"use client";

/** نظرة المنصة — عدادات وتجميعات فقط (لا محتوى سريرياً — نفس قيد DOC-06 على المنصة). */

import Link from "next/link";
import { useEffect, useState } from "react";
import { SaShell } from "@/components/SaShell";
import { ApiError } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { saApi } from "@/lib/sa";
import type { SaOverview } from "@/lib/types";

function fmtSar(value: string): string {
  const num = Number(value);
  if (Number.isNaN(num)) return value;
  return num.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function OverviewInner() {
  const { L, lang } = useLang();
  const [data, setData] = useState<SaOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const body = await saApi<SaOverview>("/overview");
        setData(body.data);
      } catch (err) {
        setError(err instanceof ApiError ? `${err.text(lang)} (${err.code})` : L("تعذر الاتصال بالخادم", "Could not reach the server"));
      }
    })();
  }, [lang, L]);

  if (error !== null) return <div className="grid-empty">{error}</div>;
  if (data === null) return <div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div>;

  return (
    <>
      <h2 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 10px" }}>{L("المنشآت", "Facilities")}</h2>
      <div className="stat-grid">
        <Link href="/sa/facilities" style={{ textDecoration: "none", color: "inherit" }}>
          <div className="card" style={{ borderColor: "#C9A227" }}>
            <div className="stat-label">{L("إجمالي المنشآت", "Total facilities")}</div>
            <div className="stat-value num">{data.facilities.total}</div>
          </div>
        </Link>
        <div className="card">
          <div className="stat-label">{L("نشطة", "Active")}</div>
          <div className="stat-value num" style={{ color: "#2E9E5B" }}>{data.facilities.active}</div>
        </div>
        <div className="card">
          <div className="stat-label">{L("معلّقة", "Suspended")}</div>
          <div className="stat-value num" style={{ color: "#B07D10" }}>{data.facilities.suspended}</div>
        </div>
        <div className="card">
          <div className="stat-label">{L("مؤرشفة", "Archived")}</div>
          <div className="stat-value num" style={{ color: "#5B7280" }}>{data.facilities.archived}</div>
        </div>
      </div>

      <h2 style={{ fontSize: 16, fontWeight: 700, margin: "22px 0 10px" }}>{L("المستخدمون والمقاعد", "Users & seats")}</h2>
      <div className="stat-grid">
        <div className="card">
          <div className="stat-label">{L("دكاترة نشطون (مقاعد مستهلكة)", "Active doctors (seats used)")}</div>
          <div className="stat-value num">{data.users.doctors_active}</div>
        </div>
        <div className="card">
          <div className="stat-label">{L("إجمالي الدكاترة", "Total doctors")}</div>
          <div className="stat-value num">{data.users.doctors_total}</div>
        </div>
        <div className="card">
          <div className="stat-label">{L("أدمنات المنشآت", "Facility admins")}</div>
          <div className="stat-value num">{data.users.admins_total}</div>
        </div>
        <div className="card">
          <div className="stat-label">{L("مقاعد مباعة", "Seats sold")}</div>
          <div className="stat-value num" style={{ color: "#0A5C64" }}>{data.seats_sold}</div>
        </div>
      </div>

      <h2 style={{ fontSize: 16, fontWeight: 700, margin: "22px 0 10px" }}>{L("الفوترة والتحصيل", "Billing & collection")}</h2>
      <div className="stat-grid">
        <div className="card" style={{ borderColor: "#C0392B" }}>
          <div className="stat-label">{L("مستحق غير محصّل (شامل الضريبة)", "Outstanding incl. VAT")}</div>
          <div className="stat-value"><bdi className="num">{fmtSar(data.invoices.outstanding_sar)}</bdi> <span style={{ fontSize: 13 }}>SAR</span></div>
          <div style={{ fontSize: 12.5, color: "#5B7280", marginTop: 4 }}>
            {L("مستحقة:", "Due:")} <span className="num">{data.invoices.due}</span> · {L("متأخرة:", "Overdue:")} <span className="num" style={{ color: "#C0392B", fontWeight: 700 }}>{data.invoices.overdue}</span>
          </div>
        </div>
        <div className="card" style={{ borderColor: "#2E9E5B" }}>
          <div className="stat-label">{L("محصّل هذا الشهر", "Collected this month")}</div>
          <div className="stat-value"><bdi className="num">{fmtSar(data.invoices.collected_this_month_sar)}</bdi> <span style={{ fontSize: 13 }}>SAR</span></div>
        </div>
        <div className="card">
          <div className="stat-label">{L("إجمالي المحصّل", "Total collected")}</div>
          <div className="stat-value"><bdi className="num">{fmtSar(data.invoices.collected_sar)}</bdi> <span style={{ fontSize: 13 }}>SAR</span></div>
          <div style={{ fontSize: 12.5, color: "#5B7280", marginTop: 4 }}>
            {L("فواتير مسددة:", "Paid invoices:")} <span className="num">{data.invoices.paid}</span>
          </div>
        </div>
        <Link href="/sa/invoices?status=overdue" style={{ textDecoration: "none", color: "inherit" }}>
          <div className="card">
            <div className="stat-label">{L("فواتير متأخرة", "Overdue invoices")}</div>
            <div className="stat-value num" style={{ color: data.invoices.overdue > 0 ? "#C0392B" : "#2E9E5B" }}>
              {data.invoices.overdue}
            </div>
            <div style={{ fontSize: 12.5, color: "#5B7280", marginTop: 4 }}>{L("فتح قائمة الفواتير ←", "Open invoices list →")}</div>
          </div>
        </Link>
      </div>

      <div className="info-box" style={{ marginTop: 18 }}>
        {L("الفوترة حسب عدد الدكاترة النشطين × سعر مقعد الباقة · كل أفعال المنصة تُدوَّن في سجل تدقيق المنشأة المعنية.",
           "Billing is active doctors × plan seat price · every platform action is recorded in the target facility's audit log.")}
      </div>
    </>
  );
}

export default function SaOverviewPage() {
  const { L } = useLang();
  return (
    <SaShell title={L("نظرة المنصة", "Platform overview")}>
      <main className="page-wrap narrow">
        <OverviewInner />
      </main>
    </SaShell>
  );
}
