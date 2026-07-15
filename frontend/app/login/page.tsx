"use client";

/** الصفحة 1 — الدخول: W-001 (دخول) + W-006 (انتهاء الجلسة) + W-206 (استعادة كلمة مرور الأدمن)
 *  الحالات داخل صفحة واحدة (خريطة الدمج DOC-10 §٤) — ثنائية اللغة (D-30). */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ApiError, api, getSessionUser, setSession } from "@/lib/api";
import { LangToggle, useLang } from "@/lib/i18n";
import type { SessionUser } from "@/lib/types";
import { Logo } from "@/components/Shell";
import { Field, SpecBadge, ToastProvider, useToast } from "@/components/ui";

type Mode = "login" | "expired" | "forgot" | "forgot_sent" | "reset";

function LoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();
  const { L, lang } = useLang();

  const [mode, setMode] = useState<Mode>("login");
  const [facility, setFacility] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // استعادة كلمة المرور (W-206)
  const [commercialReg, setCommercialReg] = useState("");
  const [adminUsername, setAdminUsername] = useState("");
  // إتمام الاستعادة برابط البريد
  const [newPassword, setNewPassword] = useState("");

  useEffect(() => {
    if (params.get("expired") === "1") setMode("expired");
    if (params.get("reset_token") !== null) setMode("reset");
  }, [params]);

  const doLogin = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = await api<{ access_token: string; user: SessionUser }>("/auth/login", {
        method: "POST",
        body: { facility, username, password },
      });
      setSession(body.data.access_token, body.data.user);
      const roleLabel = body.data.user.role === "admin" ? L("أدمن المنشأة", "facility admin") : L("دكتور", "doctor");
      toast(L(`مرحباً ${body.data.user.full_name} — دخلت بدور ${roleLabel}`,
              `Welcome ${body.data.user.full_name} — signed in as ${roleLabel}`));
      router.push(body.data.user.role === "admin" ? "/admin" : "/doctor");
    } catch (err) {
      setError(err instanceof ApiError ? `${err.text(lang)} (${err.code})` : L("تعذر الاتصال بالخادم", "Could not reach the server"));
    } finally {
      setBusy(false);
    }
  };

  const doForgot = async () => {
    setBusy(true);
    try {
      await api("/auth/forgot-password", {
        method: "POST",
        body: { commercial_reg: commercialReg, username: adminUsername },
      });
      setMode("forgot_sent");
      toast(L("أُرسل رابط الاستعادة لبريد الأدمن — صالح 30 دقيقة ويُسجّل في التدقيق",
              "Reset link sent to the admin email — valid for 30 minutes, logged in the audit trail"));
    } catch {
      setMode("forgot_sent"); // استجابة عامة موحدة لا تكشف وجود الحساب
    } finally {
      setBusy(false);
    }
  };

  const doReset = async () => {
    setBusy(true);
    setError(null);
    try {
      await api("/auth/reset-password", {
        method: "POST",
        body: { token: params.get("reset_token") ?? "", new_password: newPassword },
      });
      toast(L("عُيّنت كلمة المرور الجديدة — سجّل الدخول", "New password set — please sign in"));
      setMode("login");
    } catch (err) {
      setError(err instanceof ApiError ? `${err.text(lang)} (${err.code})` : L("تعذر الاتصال", "Connection failed"));
      if (err instanceof ApiError && err.code === "MDF-4014") setMode("forgot");
    } finally {
      setBusy(false);
    }
  };

  const tryRefreshSession = async () => {
    try {
      const body = await api<{ access_token: string }>("/auth/refresh", { method: "POST" });
      const user = getSessionUser();
      if (user !== null) {
        setSession(body.data.access_token, user);
        toast(L("جُدّدت الجلسة بصمت دون فقدان العمل (MDF-4012)", "Session renewed silently — no work lost (MDF-4012)"));
        router.push(user.role === "admin" ? "/admin" : "/doctor");
        return;
      }
      setMode("login");
    } catch {
      toast(L("تعذر التجديد الصامت — سجّل الدخول من جديد", "Silent renewal failed — please sign in again"));
      setMode("login");
    }
  };

  return (
    <main style={{ minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <LangToggle floating />
      <div style={{ textAlign: "center", marginBottom: 18 }}>
        <div style={{ transform: "scale(1.5)", transformOrigin: "center bottom" }}><Logo /></div>
        <p style={{ color: "#5B7280", fontSize: 14, margin: "10px 0 0" }}>
          {L("التوثيق السريري الذكي — من الاستشارة إلى ملف المريض", "Intelligent clinical documentation — from consultation to patient record")}
        </p>
      </div>

      <div className="card" style={{ width: "min(420px,94vw)", padding: "26px 24px", position: "relative" }}>
        {mode === "login" ? (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <h1 style={{ fontSize: 18, fontWeight: 700, color: "#0A5C64", margin: 0, flex: 1 }}>{L("تسجيل الدخول", "Sign in")}</h1>
              <SpecBadge id="W-001" />
            </div>
            <form onSubmit={(event) => { event.preventDefault(); void doLogin(); }}>
              <Field label={L("المنشأة", "Facility")} placeholder={L("اسم المنشأة أو السجل التجاري", "Facility name or commercial registration")}
                value={facility} onChange={(event) => setFacility(event.target.value)} required />
              <Field label={L("اسم المستخدم", "Username")} ltr placeholder="dr.username" value={username}
                onChange={(event) => setUsername(event.target.value)} required />
              <Field label={L("كلمة المرور", "Password")} ltr type="password" placeholder="••••••••" value={password}
                onChange={(event) => setPassword(event.target.value)} required />
              {error !== null ? (
                <p style={{ color: "#C0392B", fontSize: 12.5, fontWeight: 700, margin: "10px 0 0" }}>{error}</p>
              ) : null}
              <button type="submit" className="btn big" style={{ width: "100%", marginTop: 16 }} disabled={busy}>
                {busy ? <span className="spinner" /> : null} {L("دخول", "Sign in")}
              </button>
            </form>
            <button className="btn-ghost" style={{ display: "block", margin: "12px auto 0", textDecoration: "underline" }}
              onClick={() => setMode("forgot")}>
              {L("نسيت كلمة المرور؟ (أدمن المنشأة)", "Forgot password? (facility admin)")}
            </button>
            <p style={{ fontSize: 12.5, color: "#5B7280", textAlign: "center", margin: "14px 0 0" }}>
              {L("منشأة جديدة؟", "New facility?")} <Link href="/register">{L("سجّل منشأتك واحجز مقاعد دكاترتك", "Register your facility and reserve doctor seats")}</Link>
            </p>
          </>
        ) : null}

        {mode === "expired" ? (
          <div style={{ textAlign: "center" }}>
            <div style={{ position: "absolute", top: 12, insetInlineStart: 12 }}><SpecBadge id="W-006" /></div>
            <div style={{ width: 52, height: 52, borderRadius: 999, background: "#FDF3E3", display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#B07D10" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
            </div>
            <h1 style={{ fontSize: 18, fontWeight: 700, color: "#0A5C64", margin: "10px 0 6px" }}>{L("انتهت جلستك", "Your session has expired")}</h1>
            <p style={{ fontSize: 14, color: "#5B7280", margin: "0 0 16px" }}>
              {L("انقضت مدة الرمز (30 دقيقة). يمكن تجديد الجلسة بصمت دون فقدان العمل الجاري — وفق",
                 "The token lifetime (30 minutes) elapsed. The session can renew silently without losing work — per")} <bdi>MDF-4012</bdi> {L("و", "and")} <bdi>/auth/refresh</bdi>.
            </p>
            <button className="btn big" style={{ width: "100%" }} onClick={() => void tryRefreshSession()}>
              {L("تجديد الجلسة والمتابعة", "Renew session & continue")}
            </button>
            <button className="btn-secondary" style={{ width: "100%", marginTop: 10 }} onClick={() => setMode("login")}>
              {L("تسجيل الدخول من جديد", "Sign in again")}
            </button>
          </div>
        ) : null}

        {mode === "forgot" ? (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <h1 style={{ fontSize: 18, fontWeight: 700, color: "#0A5C64", margin: 0, flex: 1 }}>
                {L("استعادة كلمة المرور — أدمن المنشأة", "Password recovery — facility admin")}
              </h1>
              <SpecBadge id="W-206" />
            </div>
            <p style={{ fontSize: 12.5, color: "#5B7280", margin: "6px 0 0" }}>
              {L("يُرسل رابط استعادة صالح لمدة 30 دقيقة إلى بريد الأدمن المسجّل عند التسجيل.",
                 "A reset link valid for 30 minutes is sent to the admin email registered at sign-up.")}
            </p>
            <form onSubmit={(event) => { event.preventDefault(); void doForgot(); }}>
              <Field label={L("السجل التجاري للمنشأة", "Facility commercial registration")} ltr placeholder="1010XXXXXX" value={commercialReg}
                onChange={(event) => setCommercialReg(event.target.value)} required />
              <Field label={L("اسم مستخدم الأدمن", "Admin username")} ltr placeholder="admin.username" value={adminUsername}
                onChange={(event) => setAdminUsername(event.target.value)} required />
              <button type="submit" className="btn big" style={{ width: "100%", marginTop: 16 }} disabled={busy}>
                {L("إرسال رابط الاستعادة", "Send reset link")}
              </button>
            </form>
            <div className="info-box" style={{ marginTop: 12 }}>
              {L("الدكاترة لا يستخدمون هذه الصفحة — أدمن المنشأة يعيد تعيين كلماتهم من صفحة الدكاترة (FR-204).",
                 "Doctors do not use this page — the facility admin resets their passwords from the Doctors page (FR-204).")}
            </div>
            <button className="btn-secondary" style={{ width: "100%", marginTop: 12 }} onClick={() => setMode("login")}>
              {L("العودة للدخول", "Back to sign in")}
            </button>
          </>
        ) : null}

        {mode === "forgot_sent" ? (
          <div style={{ textAlign: "center" }}>
            <div style={{ position: "absolute", top: 12, insetInlineStart: 12 }}><SpecBadge id="W-206" /></div>
            <div style={{ width: 52, height: 52, borderRadius: 999, background: "#E8F6EE", display: "inline-flex", alignItems: "center", justifyContent: "center", color: "#2E9E5B", fontSize: 22, fontWeight: 800 }}>✓</div>
            <h1 style={{ fontSize: 18, fontWeight: 700, color: "#0A5C64", margin: "10px 0 6px" }}>{L("أُرسل رابط الاستعادة", "Reset link sent")}</h1>
            <p style={{ fontSize: 14, color: "#5B7280", margin: "0 0 16px" }}>
              {L("تحقق من بريد الأدمن — الرابط صالح 30 دقيقة ولاستخدام واحد، وتُسجّل العملية في سجل التدقيق.",
                 "Check the admin inbox — the link is valid for 30 minutes, single-use, and the operation is audit-logged.")}
            </p>
            <button className="btn-secondary" style={{ width: "100%" }} onClick={() => setMode("login")}>{L("العودة للدخول", "Back to sign in")}</button>
          </div>
        ) : null}

        {mode === "reset" ? (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <h1 style={{ fontSize: 18, fontWeight: 700, color: "#0A5C64", margin: 0, flex: 1 }}>{L("تعيين كلمة مرور جديدة", "Set a new password")}</h1>
              <SpecBadge id="W-206" />
            </div>
            <form onSubmit={(event) => { event.preventDefault(); void doReset(); }}>
              <Field label={L("كلمة المرور الجديدة", "New password")} ltr type="password" placeholder="••••••••" minLength={8}
                value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required />
              {error !== null ? (
                <p style={{ color: "#C0392B", fontSize: 12.5, fontWeight: 700, margin: "10px 0 0" }}>{error}</p>
              ) : null}
              <button type="submit" className="btn big" style={{ width: "100%", marginTop: 16 }} disabled={busy}>{L("حفظ ودخول", "Save & sign in")}</button>
            </form>
          </>
        ) : null}
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <ToastProvider>
      <Suspense>
        <LoginInner />
      </Suspense>
    </ToastProvider>
  );
}
