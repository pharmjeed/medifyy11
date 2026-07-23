"use client";

/** دخول السوبر أدمن — بوابة مالك ميديفاي (منفصلة كلياً عن دخول المنشآت W-001). */

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { LangToggle, useLang } from "@/lib/i18n";
import { saApi, setSaSession } from "@/lib/sa";
import type { SaAdmin } from "@/lib/sa";
import { Logo } from "@/components/Shell";
import { Field, ToastProvider, useToast } from "@/components/ui";

/** رسالة خطأ ثنائية اللغة — تُحسم عند العرض كي تتبع تبديل اللغة. */
type ErrorText = { ar: string; en: string };

function SaLoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();
  const { L, lang } = useLang();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [needTotp, setNeedTotp] = useState(false);
  const [error, setError] = useState<ErrorText | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (params.get("expired") === "1") {
      setError({ ar: "انتهت الجلسة — سجّل الدخول من جديد", en: "Session expired — please sign in again" });
    }
  }, [params]);

  const doLogin = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = await saApi<{ access_token: string; admin: SaAdmin }>("/auth/login", {
        method: "POST",
        body: { username, password, ...(totpCode ? { totp_code: totpCode } : {}) },
      });
      setSaSession(body.data.access_token, body.data.admin);
      toast(L(`مرحباً ${body.data.admin.full_name} — لوحة المنصة`, `Welcome ${body.data.admin.full_name} — platform console`));
      router.push("/sa");
    } catch (err) {
      if (err instanceof ApiError && err.code === "MDF-4015") {
        // الحساب محمي بمصادقة ثنائية — اطلب الرمز (DOC-20 §١.٣)
        setNeedTotp(true);
        setError(totpCode
          ? { ar: "رمز المصادقة غير صحيح — أدخل الرمز الحالي من تطبيق المصادقة", en: "Incorrect code — enter the current code from your authenticator app" }
          : { ar: "الحساب محمي بمصادقة ثنائية — أدخل رمز تطبيق المصادقة", en: "This account is 2FA-protected — enter your authenticator code" });
      } else {
        setError(err instanceof ApiError
          ? { ar: `${err.text("ar")} (${err.code})`, en: `${err.text("en")} (${err.code})` }
          : { ar: "تعذر الاتصال بالخادم", en: "Could not reach the server" });
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <main style={{ minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <LangToggle floating />
      <div style={{ textAlign: "center", marginBottom: 18 }}>
        <div style={{ transform: "scale(1.5)", transformOrigin: "center bottom" }}><Logo /></div>
        <p style={{ color: "#5c7096", fontSize: 14, margin: "10px 0 0" }}>
          {L("لوحة المنصة — إدارة المنشآت والباقات والمدفوعات", "Platform console — facilities, plans & payments management")}
        </p>
      </div>

      <div className="card" style={{ width: "min(420px,94vw)", padding: "26px 24px", position: "relative", borderTop: "3px solid #00c2b8" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <h1 style={{ fontSize: 18, fontWeight: 700, color: "#005a55", margin: 0, flex: 1 }}>
            {L("دخول السوبر أدمن", "Super admin sign in")}
          </h1>
          <span className="badge" style={{ background: "#00c2b8", color: "#0c1a36", fontWeight: 800 }}>
            {L("مالك المنصة", "Owner")}
          </span>
        </div>
        <form onSubmit={(event) => { event.preventDefault(); void doLogin(); }}>
          <Field label={L("اسم المستخدم", "Username")} ltr placeholder="owner" value={username}
            name="username" autoComplete="username"
            onChange={(event) => setUsername(event.target.value)} required />
          <Field label={L("كلمة المرور", "Password")} ltr type="password" placeholder="••••••••" value={password}
            name="password" autoComplete="current-password"
            onChange={(event) => setPassword(event.target.value)} required />
          {needTotp ? (
            <Field label={L("رمز المصادقة الثنائية (أو رمز استرداد)", "2FA code (or a recovery code)")} ltr
              placeholder="123456" value={totpCode} autoComplete="one-time-code" autoFocus
              onChange={(event) => setTotpCode(event.target.value)} required />
          ) : null}
          {error !== null ? (
            <p style={{ color: "#d94b4b", fontSize: 12.5, fontWeight: 700, margin: "10px 0 0" }}>{lang === "ar" ? error.ar : error.en}</p>
          ) : null}
          <button type="submit" className="btn big" style={{ width: "100%", marginTop: 16 }} disabled={busy}>
            {busy ? <span className="spinner" /> : null} {L("دخول", "Sign in")}
          </button>
        </form>
        <div className="info-box" style={{ marginTop: 14 }}>
          {L("هذه البوابة لمالك ميديفاي حصراً — حسابات المنشآت تدخل من صفحة الدخول الاعتيادية.",
             "This gate is exclusively for the Medify owner — facility accounts use the regular sign-in page.")}
        </div>
      </div>
    </main>
  );
}

export default function SaLoginPage() {
  return (
    <ToastProvider>
      <Suspense>
        <SaLoginInner />
      </Suspense>
    </ToastProvider>
  );
}
