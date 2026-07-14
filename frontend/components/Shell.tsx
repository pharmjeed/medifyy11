"use client";

/** الهيكل العام: الشريط العلوي + التنقل بالدور + مركز الإشعارات W-003 (مكوّن عرضي لا صفحة). */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, clearSession, getSessionUser, getToken } from "@/lib/api";
import type { NotificationRow, SessionUser } from "@/lib/types";
import { ErrorScreenProvider, SpecBadge, ToastProvider, fmtDateTime, initials, useToast } from "./ui";

const ADMIN_NAV = [
  { href: "/admin", label: "لوحة الأدمن" },
  { href: "/admin/clinics", label: "العيادات" },
  { href: "/admin/doctors", label: "الدكاترة" },
  { href: "/admin/subscription", label: "المقاعد والفوترة" },
  { href: "/admin/settings", label: "إعدادات المنشأة" },
  { href: "/admin/analytics", label: "التحليلات" },
  { href: "/admin/audit", label: "سجل التدقيق" },
];
const DOCTOR_NAV = [
  { href: "/doctor", label: "رئيسة الدكتور" },
  { href: "/doctor/visits", label: "سجل الزيارات" },
  { href: "/doctor/templates", label: "قوالب التلخيص" },
  { href: "/doctor/visits/new", label: "زيارة جديدة" },
];

export function Logo() {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
      <svg viewBox="0 0 44 30" width="30" height="21" aria-hidden="true">
        <path d="M3,26 C15,25 27,19 41,4" fill="none" stroke="#0E7C86" strokeWidth="3.6" strokeLinecap="round" />
        <circle cx="41" cy="4" r="3" fill="#C9A227" />
      </svg>
      <bdi className="ui" style={{ fontSize: 18, fontWeight: 800, color: "#0A5C64" }}>Medify</bdi>
    </span>
  );
}

const KIND_ACTION: Record<string, { label: string; href: (payload: Record<string, unknown>) => string }> = {
  "dr.summary_ready": { label: "فتح المراجعة", href: (p) => `/doctor/visits/${String(p["visit_id"] ?? "")}/review` },
  "dr.analysis_failed": { label: "فتح المراجعة", href: (p) => `/doctor/visits/${String(p["visit_id"] ?? "")}/review` },
  "dr.safety_flag": { label: "فتح المراجعة", href: (p) => `/doctor/visits/${String(p["visit_id"] ?? "")}/review` },
  "dr.upload_success": { label: "سجل الزيارات", href: () => "/doctor/visits" },
  "dr.upload_failed": { label: "سجل الزيارات", href: () => "/doctor/visits" },
  "dr.password_reset": { label: "الملف الشخصي", href: () => "/profile" },
  "ad.upload_failed": { label: "لوحة الأدمن", href: () => "/admin" },
  "ad.integration_down": { label: "إعدادات الربط", href: () => "/admin/settings" },
  "ad.seats_exhausted": { label: "المقاعد", href: () => "/admin/subscription" },
  "ad.payment_failed": { label: "الفواتير", href: () => "/admin/subscription" },
  "ad.renewal_upcoming": { label: "الفواتير", href: () => "/admin/subscription" },
  "ad.retention_purge": { label: "سجل التدقيق", href: () => "/admin/audit" },
};

const KIND_TITLE: Record<string, string> = {
  "dr.summary_ready": "اكتمل توليد الملخص والإرشاد",
  "dr.analysis_failed": "فشل التحليل — الملخص متاح بلا إرشادات",
  "dr.upload_success": "تأكيد رفع الزيارة لنظام المستشفى",
  "dr.upload_failed": "فشل نهائي لرفع زيارة",
  "dr.safety_flag": "إرشاد سلامة بانتظار الحسم",
  "dr.password_reset": "أعاد الأدمن تعيين كلمة مرورك",
  "ad.upload_failed": "فشل رفع نهائي لزيارة",
  "ad.integration_down": "فشل اختبار الاتصال الدوري",
  "ad.seats_exhausted": "محاولة إنشاء دكتور بلا مقاعد",
  "ad.payment_failed": "تعثر سداد",
  "ad.renewal_upcoming": "تجديد الاشتراك قريباً",
  "ad.retention_purge": "تقرير الحذف الآلي للتسجيلات",
};

const PRIORITY_CHIP: Record<string, { label: string; bg: string; fg: string }> = {
  critical: { label: "حرجة", bg: "#FDEEEE", fg: "#C0392B" },
  important: { label: "مهمة", bg: "#FDF3E3", fg: "#B07D10" },
  normal: { label: "عادية", bg: "rgba(42,111,151,.12)", fg: "#2A6F97" },
};

function NotificationCenter({ open, onClose, onUnreadChange }: {
  open: boolean;
  onClose: () => void;
  onUnreadChange: (count: number) => void;
}) {
  const [rows, setRows] = useState<NotificationRow[]>([]);
  const toast = useToast();
  const router = useRouter();

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
      <div style={{ position: "fixed", inset: 0, zIndex: 60, background: "rgba(15,34,51,.25)" }} onClick={onClose} />
      <div style={{
        position: "fixed", top: 70, insetInlineEnd: "auto", left: 18, zIndex: 61,
        width: "min(380px,92vw)", maxHeight: "74vh", overflowY: "auto", background: "#fff",
        border: "1px solid #D7E3E8", borderRadius: 12, boxShadow: "0 18px 44px rgba(15,34,51,.22)", animation: "mIn .18s ease",
      }}>
        <div style={{ padding: "14px 16px", borderBottom: "1px solid #D7E3E8", position: "sticky", top: 0, background: "#fff", display: "flex", alignItems: "center", gap: 8 }}>
          <strong style={{ fontSize: 16, flex: 1 }}>مركز الإشعارات</strong>
          <SpecBadge id="W-003" />
          <button className="btn-ghost" onClick={async () => {
            for (const row of rows.filter((r) => r.read_at === null)) await markRead(row.id);
            toast("حُدّدت الإشعارات كمقروءة");
          }}>تحديد الكل كمقروء</button>
          <button className="modal-close" aria-label="إغلاق" onClick={onClose}>✕</button>
        </div>
        {rows.length === 0 ? <div className="grid-empty">لا إشعارات</div> : rows.map((row) => {
          const priority = PRIORITY_CHIP[row.payload.priority ?? "normal"] ?? PRIORITY_CHIP["normal"]!;
          const action = KIND_ACTION[row.kind];
          const unread = row.read_at === null;
          return (
            <div key={row.id} style={{
              display: "flex", gap: 10, padding: "12px 16px", borderBottom: "1px solid #EAF6F7",
              background: unread ? "rgba(14,124,134,.05)" : "#fff",
            }}>
              <span style={{ width: 9, height: 9, borderRadius: 999, marginTop: 8, flexShrink: 0, background: unread ? priority.fg : "#D7E3E8" }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  <strong style={{ fontSize: 14 }}>{KIND_TITLE[row.kind] ?? row.kind}</strong>
                  <span className="badge" style={{ background: priority.bg, color: priority.fg }}>{priority.label}</span>
                </div>
                <div style={{ fontSize: 12.5, color: "#5B7280", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 2 }}>
                  <bdi>{row.kind}</bdi>
                  <span>{fmtDateTime(row.created_at)}</span>
                  {action !== undefined ? (
                    <button className="btn-ghost" onClick={() => {
                      void markRead(row.id);
                      onClose();
                      router.push(action.href(row.payload));
                    }}>{action.label}</button>
                  ) : null}
                  {unread ? <button className="btn-ghost" onClick={() => void markRead(row.id)}>تمييز كمقروء</button> : null}
                </div>
              </div>
            </div>
          );
        })}
        <div style={{ padding: "10px 16px", fontSize: 12.5, color: "#5B7280" }}>
          قناتا الإطلاق: داخل التطبيق + بريد للحرجة · لا محتوى سريرياً في الإشعارات (DOC-12).
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

  useEffect(() => {
    const session = getSessionUser();
    if (session === null || getToken() === null) {
      router.replace("/login");
      return;
    }
    setUser(session);
    setChecked(true);
  }, [router]);

  useEffect(() => {
    // عداد الجرس عند التحميل
    void (async () => {
      try {
        const body = await api<NotificationRow[]>("/notifications?unread_only=true&per_page=1");
        setUnread(body.meta.unread ?? 0);
      } catch { /* تجاهل */ }
    })();
  }, [pathname]);

  if (!checked || user === null) return null;

  const nav = user.role === "admin" ? ADMIN_NAV : DOCTOR_NAV;
  const roleLabel = user.role === "admin" ? "أدمن المنشأة" : "دكتور";

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
            <Link href={user.role === "admin" ? "/admin" : "/doctor"} aria-label="Medify"><Logo /></Link>
            <span className="topbar-divider" />
            <span style={{ fontSize: 16, fontWeight: 700 }}>{title}</span>
            <span style={{ flex: 1 }} />
            <button className="btn-icon" aria-label="الإشعارات" onClick={() => setNotifOpen((value) => !value)}>
              <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#0A5C64" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.7 21a2 2 0 0 1-3.4 0" />
              </svg>
              {unread > 0 ? <span className="bell-count">{unread}</span> : null}
            </button>
            <span className="user-chip">
              <span style={{ textAlign: "start" }}>
                <span style={{ display: "block", fontSize: 14, fontWeight: 700, lineHeight: 1.3 }}>{user.full_name}</span>
                <span style={{ display: "block", fontSize: 12.5, color: "#5B7280", lineHeight: 1.3 }}>{roleLabel}</span>
              </span>
              <Link href="/profile" className="avatar" aria-label="الملف الشخصي" style={{ textDecoration: "none" }}>
                {initials(user.full_name)}
              </Link>
            </span>
            <button className="btn-icon logout" aria-label="تسجيل الخروج" onClick={() => void logout()}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#C0392B" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" />
              </svg>
            </button>
          </div>
          <nav style={{ borderTop: "1px solid #EAF6F7", background: "#fff" }} aria-label="التنقل الرئيسي">
            <div style={{ maxWidth: 1160, margin: "0 auto", padding: "0 20px", display: "flex", gap: 4, overflowX: "auto" }}>
              {nav.map((item) => {
                const active = item.href === "/doctor/visits"
                  ? pathname === item.href || (pathname.startsWith("/doctor/visits/") && !pathname.startsWith("/doctor/visits/new"))
                  : pathname === item.href;
                return (
                  <Link key={item.href} href={item.href} style={{
                    padding: "9px 14px", fontSize: 14, fontWeight: 700, textDecoration: "none",
                    color: active ? "#0A5C64" : "#5B7280",
                    borderBottom: active ? "3px solid #0E7C86" : "3px solid transparent",
                  }}>{item.label}</Link>
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
