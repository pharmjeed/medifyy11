"use client";

/** الهيكل العام: الشريط العلوي + التنقل بالدور + مركز الإشعارات W-003 (مكوّن عرضي لا صفحة). */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, clearSession, getSessionUser, getToken } from "@/lib/api";
import { LangToggle, useLang } from "@/lib/i18n";
import type { NotificationRow, SessionUser } from "@/lib/types";
import { ErrorScreenProvider, SpecBadge, ToastProvider, fmtDateTime, initials, useToast } from "./ui";

const ADMIN_NAV = [
  { href: "/admin", ar: "لوحة الأدمن", en: "Admin dashboard" },
  { href: "/admin/clinics", ar: "العيادات", en: "Clinics" },
  { href: "/admin/doctors", ar: "الدكاترة", en: "Doctors" },
  { href: "/admin/subscription", ar: "المقاعد والفوترة", en: "Seats & billing" },
  { href: "/admin/settings", ar: "إعدادات المنشأة", en: "Facility settings" },
  { href: "/admin/analytics", ar: "التحليلات", en: "Analytics" },
  { href: "/admin/audit", ar: "سجل التدقيق", en: "Audit log" },
];
const DOCTOR_NAV = [
  { href: "/doctor", ar: "رئيسة الدكتور", en: "Doctor home" },
  { href: "/doctor/visits", ar: "سجل الزيارات", en: "Visits log" },
  { href: "/doctor/templates", ar: "قوالب التلخيص", en: "Templates" },
  { href: "/doctor/visits/new", ar: "زيارة جديدة", en: "New visit" },
];

/** الشعار الرسمي (wordmark الهوية) — يتبدّل مع اللغة: «ميدفاي» عربي / «Medify» لاتيني. */
export function Logo({ height = 26 }: { height?: number }) {
  const { lang, L } = useLang();
  const src = lang === "ar" ? "/brand/medify-wordmark-ar.svg" : "/brand/medify-wordmark.svg";
  return (
    /* eslint-disable-next-line @next/next/no-img-element */
    <img
      src={src}
      alt={L("ميدفاي", "Medify")}
      /* inline-block ليحترم textAlign:center في صفحات الدخول، وverticalAlign يمنع فجوة الأساس */
      style={{ height, width: "auto", display: "inline-block", verticalAlign: "middle" }}
    />
  );
}

const KIND_ACTION: Record<string, { ar: string; en: string; href: (payload: Record<string, unknown>) => string }> = {
  "dr.summary_ready": { ar: "فتح المراجعة", en: "Open review", href: (p) => `/doctor/visits/${String(p["visit_id"] ?? "")}/review` },
  "dr.analysis_failed": { ar: "فتح المراجعة", en: "Open review", href: (p) => `/doctor/visits/${String(p["visit_id"] ?? "")}/review` },
  "dr.safety_flag": { ar: "فتح المراجعة", en: "Open review", href: (p) => `/doctor/visits/${String(p["visit_id"] ?? "")}/review` },
  "dr.upload_success": { ar: "سجل الزيارات", en: "Visits log", href: () => "/doctor/visits" },
  "dr.upload_failed": { ar: "سجل الزيارات", en: "Visits log", href: () => "/doctor/visits" },
  "dr.password_reset": { ar: "الملف الشخصي", en: "Profile", href: () => "/profile" },
  "ad.upload_failed": { ar: "لوحة الأدمن", en: "Admin dashboard", href: () => "/admin" },
  "ad.integration_down": { ar: "إعدادات الربط", en: "Integration settings", href: () => "/admin/settings" },
  "ad.seats_exhausted": { ar: "المقاعد", en: "Seats", href: () => "/admin/subscription" },
  "ad.payment_failed": { ar: "الفواتير", en: "Invoices", href: () => "/admin/subscription" },
  "ad.renewal_upcoming": { ar: "الفواتير", en: "Invoices", href: () => "/admin/subscription" },
  "ad.retention_purge": { ar: "سجل التدقيق", en: "Audit log", href: () => "/admin/audit" },
};

const KIND_TITLE: Record<string, { ar: string; en: string }> = {
  "dr.summary_ready": { ar: "اكتمل توليد الملخص والإرشاد", en: "Summary & guidance generated" },
  "dr.analysis_failed": { ar: "فشل التحليل — الملخص متاح بلا إرشادات", en: "Analysis failed — summary available without guidance" },
  "dr.upload_success": { ar: "تأكيد رفع الزيارة لنظام المستشفى", en: "Visit upload to hospital system confirmed" },
  "dr.upload_failed": { ar: "فشل نهائي لرفع زيارة", en: "Visit upload failed permanently" },
  "dr.safety_flag": { ar: "إرشاد سلامة بانتظار الحسم", en: "Patient-safety guidance awaiting resolution" },
  "dr.password_reset": { ar: "أعاد الأدمن تعيين كلمة مرورك", en: "Admin reset your password" },
  "ad.upload_failed": { ar: "فشل رفع نهائي لزيارة", en: "A visit upload failed permanently" },
  "ad.integration_down": { ar: "فشل اختبار الاتصال الدوري", en: "Periodic integration test failed" },
  "ad.seats_exhausted": { ar: "محاولة إنشاء دكتور بلا مقاعد", en: "Doctor creation attempted with no seats" },
  "ad.payment_failed": { ar: "تعثر سداد", en: "Payment failed" },
  "ad.renewal_upcoming": { ar: "تجديد الاشتراك قريباً", en: "Subscription renewal upcoming" },
  "ad.retention_purge": { ar: "تقرير الحذف الآلي للتسجيلات", en: "Automatic recordings purge report" },
};

const PRIORITY_CHIP: Record<string, { ar: string; en: string; bg: string; fg: string }> = {
  critical: { ar: "حرجة", en: "Critical", bg: "#fbeaea", fg: "#d94b4b" },
  important: { ar: "مهمة", en: "Important", bg: "#fdf4e0", fg: "#9c6f00" },
  normal: { ar: "عادية", en: "Normal", bg: "rgba(42,111,151,.12)", fg: "#3b82c4" },
};

function NotificationCenter({ open, onClose, onUnreadChange }: {
  open: boolean;
  onClose: () => void;
  onUnreadChange: (count: number) => void;
}) {
  const [rows, setRows] = useState<NotificationRow[]>([]);
  const toast = useToast();
  const router = useRouter();
  const { L } = useLang();

  const load = useCallback(async () => {
    try {
      const body = await api<NotificationRow[]>("/notifications?per_page=50");
      setRows(body.data);
      onUnreadChange(body.meta.unread ?? 0);
    } catch {
      /* الجرس تحسيني — لا نعطل الهيكل */
    }
  }, [onUnreadChange]);

  useEffect(() => { void load(); }, [load, open]);

  if (!open) return null;

  const markRead = async (id: string) => {
    try {
      await api(`/notifications/${id}/read`, { method: "PATCH" });
      void load();
    } catch { /* تجاهل */ }
  };

  return (
    <>
      <div style={{ position: "fixed", inset: 0, zIndex: 60, background: "rgba(12,26,54,.25)" }} onClick={onClose} />
      <div style={{
        position: "fixed", top: 70, insetInlineEnd: "auto", left: 18, zIndex: 61,
        width: "min(380px,92vw)", maxHeight: "74vh", overflowY: "auto", background: "#fff",
        border: "1px solid #c7d1e0", borderRadius: 12, boxShadow: "0 18px 44px rgba(12,26,54,.22)", animation: "mIn .18s ease",
      }}>
        <div style={{ padding: "14px 16px", borderBottom: "1px solid #c7d1e0", position: "sticky", top: 0, background: "#fff", display: "flex", alignItems: "center", gap: 8 }}>
          <strong style={{ fontSize: 16, flex: 1 }}>{L("مركز الإشعارات", "Notification center")}</strong>
          <SpecBadge id="W-003" />
          <button className="btn-ghost" onClick={async () => {
            for (const row of rows.filter((r) => r.read_at === null)) await markRead(row.id);
            toast(L("حُدّدت الإشعارات كمقروءة", "All notifications marked as read"));
          }}>{L("تحديد الكل كمقروء", "Mark all as read")}</button>
          <button className="modal-close" aria-label={L("إغلاق", "Close")} onClick={onClose}>✕</button>
        </div>
        {rows.length === 0 ? <div className="grid-empty">{L("لا إشعارات", "No notifications")}</div> : rows.map((row) => {
          const priority = PRIORITY_CHIP[row.payload.priority ?? "normal"] ?? PRIORITY_CHIP["normal"]!;
          const action = KIND_ACTION[row.kind];
          const title = KIND_TITLE[row.kind];
          const unread = row.read_at === null;
          return (
            <div key={row.id} style={{
              display: "flex", gap: 10, padding: "12px 16px", borderBottom: "1px solid #d6f5f2",
              background: unread ? "rgba(0,115,109,.05)" : "#fff",
            }}>
              <span style={{ width: 9, height: 9, borderRadius: 999, marginTop: 8, flexShrink: 0, background: unread ? priority.fg : "#c7d1e0" }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  <strong style={{ fontSize: 14 }}>{title !== undefined ? L(title.ar, title.en) : row.kind}</strong>
                  <span className="badge" style={{ background: priority.bg, color: priority.fg }}>{L(priority.ar, priority.en)}</span>
                </div>
                <div style={{ fontSize: 12.5, color: "#5c7096", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 2 }}>
                  <bdi>{row.kind}</bdi>
                  <span>{fmtDateTime(row.created_at)}</span>
                  {action !== undefined ? (
                    <button className="btn-ghost" onClick={() => {
                      void markRead(row.id);
                      onClose();
                      router.push(action.href(row.payload));
                    }}>{L(action.ar, action.en)}</button>
                  ) : null}
                  {unread ? <button className="btn-ghost" onClick={() => void markRead(row.id)}>{L("تمييز كمقروء", "Mark as read")}</button> : null}
                </div>
              </div>
            </div>
          );
        })}
        <div style={{ padding: "10px 16px", fontSize: 12.5, color: "#5c7096" }}>
          {L("قناتا الإطلاق: داخل التطبيق + بريد للحرجة · لا محتوى سريرياً في الإشعارات (DOC-12).",
             "Channels: in-app + email for critical · no clinical content in notifications (DOC-12).")}
        </div>
      </div>
    </>
  );
}

export function Shell({ title, children }: { title: string; children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [checked, setChecked] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const router = useRouter();
  const pathname = usePathname();
  const { L } = useLang();

  useEffect(() => {
    const session = getSessionUser();
    if (session === null || getToken() === null) {
      router.replace("/login");
      return;
    }
    setUser(session);
    setChecked(true);
  }, [router]);

  // حارس الدور (طبقة تجربة استخدام فوق حراس الخادم admin_only/doctor_only):
  // كل قسم لدوره — دكتور يفتح /admin (bookmark/رابط قديم) يُعاد بهدوء للوحته والعكس،
  // بدل نافذة MDF-4031. الأمان الفعلي يبقى على الخادم؛ هذا لتجربة الاستخدام فقط.
  const section = pathname.startsWith("/admin") ? "admin" : pathname.startsWith("/doctor") ? "doctor" : null;
  const roleMismatch = user !== null && section !== null && user.role !== section;

  useEffect(() => {
    if (roleMismatch && user !== null) {
      router.replace(user.role === "admin" ? "/admin" : "/doctor");
    }
  }, [roleMismatch, user, router]);

  useEffect(() => {
    // عداد الجرس عند التحميل
    void (async () => {
      try {
        const body = await api<NotificationRow[]>("/notifications?unread_only=true&per_page=1");
        setUnread(body.meta.unread ?? 0);
      } catch { /* تجاهل */ }
    })();
  }, [pathname]);

  if (!checked || user === null || roleMismatch) return null;

  const nav = user.role === "admin" ? ADMIN_NAV : DOCTOR_NAV;
  const roleLabel = user.role === "admin" ? L("أدمن المنشأة", "Facility admin") : L("دكتور", "Doctor");

  const logout = async () => {
    try { await api("/auth/logout", { method: "POST" }); } catch { /* تجاهل */ }
    clearSession();
    router.push("/login");
  };

  return (
    <ToastProvider>
      <ErrorScreenProvider>
        <header className="topbar">
          <div className="topbar-inner">
            <Link href={user.role === "admin" ? "/admin" : "/doctor"} aria-label={L("ميدفاي — الصفحة الرئيسية", "Medify — Home")}><Logo /></Link>
            <span className="topbar-divider" />
            <span style={{ fontSize: 16, fontWeight: 700 }}>{title}</span>
            <span style={{ flex: 1 }} />
            <LangToggle />
            <button className="btn-icon" aria-label={L("الإشعارات", "Notifications")} onClick={() => setNotifOpen((value) => !value)}>
              <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#005a55" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.7 21a2 2 0 0 1-3.4 0" />
              </svg>
              {unread > 0 ? <span className="bell-count">{unread}</span> : null}
            </button>
            <span className="user-chip">
              <span style={{ textAlign: "start" }}>
                <span style={{ display: "block", fontSize: 14, fontWeight: 700, lineHeight: 1.3 }}>{user.full_name}</span>
                <span style={{ display: "block", fontSize: 12.5, color: "#5c7096", lineHeight: 1.3 }}>{roleLabel}</span>
              </span>
              <Link href="/profile" className="avatar" aria-label={L("الملف الشخصي", "Profile")} style={{ textDecoration: "none" }}>
                {initials(user.full_name)}
              </Link>
            </span>
            <button className="btn-icon logout" aria-label={L("تسجيل الخروج", "Sign out")} onClick={() => void logout()}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#d94b4b" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" />
              </svg>
            </button>
          </div>
          <nav style={{ borderTop: "1px solid #d6f5f2", background: "#fff" }} aria-label={L("التنقل الرئيسي", "Main navigation")}>
            <div style={{ maxWidth: 1160, margin: "0 auto", padding: "0 20px", display: "flex", gap: 4, overflowX: "auto" }}>
              {nav.map((item) => {
                const active = item.href === "/doctor/visits"
                  ? pathname === item.href || (pathname.startsWith("/doctor/visits/") && !pathname.startsWith("/doctor/visits/new"))
                  : pathname === item.href;
                return (
                  <Link key={item.href} href={item.href} style={{
                    padding: "9px 14px", fontSize: 14, fontWeight: 700, textDecoration: "none",
                    color: active ? "#005a55" : "#5c7096",
                    borderBottom: active ? "3px solid #00736d" : "3px solid transparent",
                    whiteSpace: "nowrap",
                  }}>{L(item.ar, item.en)}</Link>
                );
              })}
            </div>
          </nav>
        </header>
        <NotificationCenter open={notifOpen} onClose={() => setNotifOpen(false)} onUnreadChange={setUnread} />
        {children}
      </ErrorScreenProvider>
    </ToastProvider>
  );
}
