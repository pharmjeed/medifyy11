"use client";

/** الصفحة 11 — رئيسة الدكتور W-201 (FR-804): تحية + إحصاءات اليوم + زيارات اليوم. */

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, getSessionUser } from "@/lib/api";
import type { SessionUser, Template, VisitRow } from "@/lib/types";
import { Shell } from "@/components/Shell";
import { SpecBar, VisitStateBadge, useErrorScreen } from "@/components/ui";

/** زر الإجراء حسب الحالة (نفس قاعدة سجل الزيارات). */
function actionFor(row: VisitRow): { label: string; href: string } | null {
  switch (row.state) {
    case "in_review": return { label: "فتح المراجعة", href: `/doctor/visits/${row.id}/review` };
    case "uploaded": return { label: "عرض للقراءة", href: `/doctor/visits?open=${row.id}` };
    case "upload_failed": return { label: "إعادة المحاولة", href: `/doctor/visits/${row.id}/review` };
    case "draft": return { label: "استئناف", href: `/doctor/visits/new?resume=${row.id}` };
    case "summarized": return { label: "بدء المراجعة", href: `/doctor/visits/${row.id}/review` };
    default: return null;
  }
}

const HOME_GRID = ".9fr 1.8fr 1fr 1.1fr 1.1fr";

function DoctorHomeInner() {
  const showError = useErrorScreen();
  const [user, setUser] = useState<SessionUser | null>(null);
  const [now, setNow] = useState<Date | null>(null);
  const [rows, setRows] = useState<VisitRow[] | null>(null);
  const [templates, setTemplates] = useState<Template[] | null>(null);

  useEffect(() => {
    setUser(getSessionUser());
    setNow(new Date());
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const [visitsBody, templatesBody] = await Promise.all([
          api<VisitRow[]>("/visits?per_page=100"),
          api<Template[]>("/templates"),
        ]);
        setRows(visitsBody.data);
        setTemplates(templatesBody.data);
      } catch (err) {
        showError(err);
      }
    })();
  }, [showError]);

  const all = rows ?? [];
  const todayStamp = (now ?? new Date()).toDateString();
  const todayRows = all.filter((row) => new Date(row.created_at).toDateString() === todayStamp);
  const inReviewCount = all.filter((row) => row.state === "in_review").length;
  const uploadedCount = all.filter((row) => row.state === "uploaded").length;
  const defaultTemplate = (templates ?? []).find((tpl) => tpl.is_default);

  const greeting = now !== null && now.getHours() < 12 ? "صباح الخير" : "مساء الخير";
  const dateLine = now !== null
    ? now.toLocaleDateString("ar", { weekday: "long", day: "numeric", month: "long", year: "numeric" })
    : "";

  return (
    <>
      <SpecBar ids="W-201" desc="الصفحة 11 — رئيسة الدكتور (FR-804)" />

      {/* الترويسة: التحية + زر بدء زيارة جديدة */}
      <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", marginBottom: 18 }}>
        <div style={{ flex: 1, minWidth: 240 }}>
          <h1 className="page-title" style={{ marginBottom: 2 }}>
            {greeting}{user !== null ? `، ${user.full_name}` : ""}
          </h1>
          <p className="page-desc" style={{ margin: 0 }}>
            {dateLine}{user !== null ? ` · عيادة الباطنة — ${user.facility_name}` : ""}
          </p>
        </div>
        <Link href="/doctor/visits/new" className="btn hero" style={{ textDecoration: "none" }}>
          <span style={{ width: 10, height: 10, borderRadius: 999, background: "#C0392B", flexShrink: 0, animation: "mBlink 1.1s ease infinite" }} />
          + بدء زيارة جديدة
        </Link>
      </div>

      {/* أربع بطاقات إحصائية */}
      <div className="stat-grid">
        <div className="card">
          <div className="stat-label">زيارات اليوم</div>
          <div className="stat-value"><span className="num">{todayRows.length}</span></div>
        </div>
        <div className="card">
          <div className="stat-label">بانتظار المراجعة</div>
          <div className="stat-value" style={{ color: "#B07D10" }}><span className="num">{inReviewCount}</span></div>
        </div>
        <div className="card">
          <div className="stat-label">مرفوعة ✓</div>
          <div className="stat-value" style={{ color: "#2E9E5B" }}><span className="num">{uploadedCount}</span></div>
        </div>
        <div className="card">
          <div className="stat-label">قالبك الافتراضي</div>
          <div style={{ fontSize: 16, fontWeight: 800, color: "#0A5C64", lineHeight: 1.6 }}>
            {defaultTemplate !== undefined ? defaultTemplate.name : "—"}
          </div>
          <Link href="/doctor/templates" className="btn-ghost" style={{ padding: 0 }}>إدارة القوالب</Link>
        </div>
      </div>

      {/* جدول زيارات اليوم */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "22px 0 10px" }}>
        <h2 style={{ fontSize: 16, fontWeight: 800, margin: 0, flex: 1 }}>زيارات اليوم</h2>
        <Link href="/doctor/visits" className="btn-ghost">السجل الكامل</Link>
      </div>
      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: HOME_GRID }}>
          <div>الوقت</div><div>المريض</div><div>الملف</div><div>الحالة</div><div>إجراء</div>
        </div>
        {rows === null ? (
          <div className="grid-empty">جارٍ التحميل…</div>
        ) : todayRows.length === 0 ? (
          <div className="grid-empty">لا زيارات اليوم بعد</div>
        ) : (
          todayRows.map((row, index) => {
            const action = actionFor(row);
            return (
              <div key={row.id} className={index % 2 === 1 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: HOME_GRID }}>
                <div><span className="num">{new Date(row.created_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}</span></div>
                <div>{row.patient_name}</div>
                <div><bdi>{row.patient_mrn}</bdi></div>
                <div><VisitStateBadge state={row.state} /></div>
                <div>
                  {action !== null ? (
                    <Link href={action.href} className="btn-row" style={{ textDecoration: "none", display: "inline-flex", alignItems: "center" }}>
                      {action.label}
                    </Link>
                  ) : (
                    <span style={{ color: "#5B7280" }}>—</span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </>
  );
}

export default function DoctorHomePage() {
  return (
    <Shell title="رئيسة الدكتور">
      <main className="page-wrap">
        <DoctorHomeInner />
      </main>
    </Shell>
  );
}
