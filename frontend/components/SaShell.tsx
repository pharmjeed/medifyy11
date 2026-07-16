"use client";

/** هيكل لوحة السوبر أدمن — شريط علوي بشارة ذهبية مميزة عن لوحات المنشآت + تنقل المنصة. */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { LangToggle, useLang } from "@/lib/i18n";
import { clearSaSession, getSaAdmin, getSaToken, saApi, saCan, setSaSession } from "@/lib/sa";
import type { SaAdmin, SaRole } from "@/lib/sa";
import { ErrorScreenProvider, ToastProvider, initials } from "./ui";
import { Logo } from "./Shell";

const SA_NAV: { href: string; ar: string; en: string; cap?: string }[] = [
  { href: "/sa", ar: "نظرة المنصة", en: "Platform overview" },
  { href: "/sa/facilities", ar: "المنشآت", en: "Facilities" },
  { href: "/sa/plans", ar: "تسعير الدكتور", en: "Doctor pricing" },
  { href: "/sa/invoices", ar: "الفواتير والمدفوعات", en: "Invoices & payments" },
  { href: "/sa/audit", ar: "سجل المنصة", en: "Platform audit" },
  { href: "/sa/admins", ar: "حسابات المنصة", en: "Platform accounts", cap: "admins.manage" },
  { href: "/sa/security", ar: "الأمان", en: "Security" },
];

const ROLE_LABEL: Record<SaRole, { ar: string; en: string }> = {
  owner: { ar: "مالك المنصة", en: "Platform owner" },
  ops: { ar: "تشغيل", en: "Operations" },
  finance: { ar: "مالية", en: "Finance" },
  support: { ar: "دعم", en: "Support" },
  read_only: { ar: "قراءة فقط", en: "Read-only" },
};

export function SaShell({ title, children }: { title: string; children: ReactNode }) {
  const [admin, setAdmin] = useState<SaAdmin | null>(null);
  const [checked, setChecked] = useState(false);
  const router = useRouter();
  const pathname = usePathname();
  const { L } = useLang();

  useEffect(() => {
    const session = getSaAdmin();
    if (session === null || getSaToken() === null) {
      router.replace("/sa/login");
      return;
    }
    setAdmin(session);
    setChecked(true);
    // حدّث الدرجة وحالة 2FA من الخادم (الدرجة تُحقن من القاعدة لا من الرمز — DOC-20 §١.٢)
    void (async () => {
      try {
        const me = await saApi<SaAdmin>("/me");
        setAdmin(me.data);
        const token = getSaToken();
        if (token) setSaSession(token, me.data);
      } catch { /* عند انتهاء الجلسة يعيد saApi التوجيه بنفسه */ }
    })();
  }, [router]);

  if (!checked || admin === null) return null;

  const logout = async () => {
    try { await saApi("/auth/logout", { method: "POST" }); } catch { /* تجاهل */ }
    clearSaSession();
    router.push("/sa/login");
  };

  return (
    <ToastProvider>
      <ErrorScreenProvider>
        <header className="topbar">
          <div className="topbar-inner">
            <Link href="/sa" aria-label="Medify"><Logo /></Link>
            <span className="badge" style={{ background: "#C9A227", color: "#0F2233", fontWeight: 800 }}>
              {L("سوبر أدمن", "Super admin")}
            </span>
            <span className="topbar-divider" />
            <span style={{ fontSize: 16, fontWeight: 700 }}>{title}</span>
            <span style={{ flex: 1 }} />
            <LangToggle />
            <span className="user-chip">
              <span style={{ textAlign: "start" }}>
                <span style={{ display: "block", fontSize: 14, fontWeight: 700, lineHeight: 1.3 }}>{admin.full_name}</span>
                <span style={{ display: "block", fontSize: 12.5, color: "#5B7280", lineHeight: 1.3 }}>
                  {L(ROLE_LABEL[admin.role]?.ar ?? admin.role, ROLE_LABEL[admin.role]?.en ?? admin.role)}
                </span>
              </span>
              <span className="avatar" style={{ background: "#C9A227", color: "#0F2233" }}>{initials(admin.full_name)}</span>
            </span>
            <button className="btn-icon logout" aria-label={L("تسجيل الخروج", "Sign out")} onClick={() => void logout()}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#C0392B" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" />
              </svg>
            </button>
          </div>
          <nav style={{ borderTop: "1px solid #EAF6F7", background: "#fff" }} aria-label={L("تنقل المنصة", "Platform navigation")}>
            <div style={{ maxWidth: 1160, margin: "0 auto", padding: "0 20px", display: "flex", gap: 4, overflowX: "auto" }}>
              {SA_NAV.filter((item) => item.cap === undefined || saCan(admin, item.cap)).map((item) => {
                const active = item.href === "/sa/facilities"
                  ? pathname === item.href || pathname.startsWith("/sa/facilities/")
                  : pathname === item.href;
                return (
                  <Link key={item.href} href={item.href} style={{
                    padding: "9px 14px", fontSize: 14, fontWeight: 700, textDecoration: "none",
                    color: active ? "#0A5C64" : "#5B7280",
                    borderBottom: active ? "3px solid #C9A227" : "3px solid transparent",
                    whiteSpace: "nowrap",
                  }}>{L(item.ar, item.en)}</Link>
                );
              })}
            </div>
          </nav>
        </header>
        {!admin.totp_enabled && pathname !== "/sa/security" ? (
          <div style={{ background: "#FDF3E3", borderBottom: "1px solid #E8D59A", padding: "8px 20px", textAlign: "center", fontSize: 13.5 }}>
            {L("المصادقة الثنائية غير مفعّلة لحسابك — إلزامية على الإنتاج قبل فتح الكونسول.", "Two-factor authentication is not enabled — mandatory on production before the console opens.")}{" "}
            <Link href="/sa/security" style={{ fontWeight: 700, color: "#8A6A12" }}>{L("فعّلها الآن ←", "Enable it now →")}</Link>
          </div>
        ) : null}
        {children}
      </ErrorScreenProvider>
    </ToastProvider>
  );
}
