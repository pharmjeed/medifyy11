"use client";

/** W-SA-12 — الأمان والمصادقة الثنائية: تفعيل TOTP، رموز الاسترداد (تُعرض مرة واحدة)، التعطيل، وتغيير كلمة المرور. */

import { useState } from "react";
import { SaShell } from "@/components/SaShell";
import { Field, useToast } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import type { Lang } from "@/lib/i18n";
import { getSaAdmin, getSaToken, saApi, setSaSession } from "@/lib/sa";
import type { SaAdmin } from "@/lib/sa";

type LFn = (ar: string, en: string) => string;

function apiErrorText(err: unknown, lang: Lang, L: LFn): string {
  return err instanceof ApiError ? `${err.text(lang)} (${err.code})` : L("تعذر الاتصال بالخادم", "Could not reach the server");
}

function refreshStoredAdmin(patch: Partial<SaAdmin>): void {
  const admin = getSaAdmin();
  const token = getSaToken();
  if (admin && token) setSaSession(token, { ...admin, ...patch });
}

function TwoFactorCard() {
  const toast = useToast();
  const { L, lang } = useLang();
  const [admin, setAdmin] = useState<SaAdmin | null>(getSaAdmin());
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);

  const startSetup = async () => {
    setBusy(true);
    try {
      const body = await saApi<{ secret: string; otpauth_uri: string }>("/me/2fa/setup", { method: "POST" });
      setSetup(body.data);
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setBusy(false);
    }
  };

  const enable = async () => {
    setBusy(true);
    try {
      const body = await saApi<{ enabled: boolean; recovery_codes: string[] }>("/me/2fa/enable", {
        method: "POST", body: { code },
      });
      setRecoveryCodes(body.data.recovery_codes);
      setSetup(null);
      setCode("");
      refreshStoredAdmin({ totp_enabled: true });
      setAdmin((current) => (current ? { ...current, totp_enabled: true } : current));
      toast(L("فُعّلت المصادقة الثنائية — احفظ رموز الاسترداد الآن", "2FA enabled — save your recovery codes now"));
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    const liveCode = window.prompt(L("أدخل رمز المصادقة الحالي لتأكيد التعطيل:", "Enter your current authenticator code to confirm disabling:"));
    if (!liveCode) return;
    setBusy(true);
    try {
      await saApi("/me/2fa/disable", { method: "POST", body: { code: liveCode } });
      refreshStoredAdmin({ totp_enabled: false });
      setAdmin((current) => (current ? { ...current, totp_enabled: false } : current));
      setRecoveryCodes(null);
      toast(L("عُطّلت المصادقة الثنائية", "2FA disabled"));
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card" style={{ padding: 18, borderColor: "#00c2b8" }}>
      <h2 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 6px" }}>
        {L("المصادقة الثنائية (TOTP)", "Two-factor authentication (TOTP)")}
      </h2>
      <p style={{ fontSize: 13, color: "#5c7096", margin: "0 0 12px" }}>
        {L("إلزامية على الإنتاج قبل فتح الكونسول — رمز من تطبيق مصادقة (Google Authenticator / Authy / 1Password).",
           "Mandatory on production before the console opens — codes from an authenticator app (Google Authenticator / Authy / 1Password).")}
      </p>

      {admin?.totp_enabled ? (
        <>
          <span className="badge success">{L("مفعّلة", "Enabled")}</span>
          <div style={{ marginTop: 12 }}>
            <button className="btn-row danger" disabled={busy} onClick={() => void disable()}>
              {L("تعطيل المصادقة الثنائية", "Disable 2FA")}
            </button>
          </div>
        </>
      ) : setup === null ? (
        <>
          <span className="badge warn">{L("غير مفعّلة", "Not enabled")}</span>
          <div style={{ marginTop: 12 }}>
            <button className="btn h40" disabled={busy} onClick={() => void startSetup()}>
              {busy ? <span className="spinner" /> : null} {L("بدء التفعيل", "Start setup")}
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="sub-box" style={{ fontSize: 13.5 }}>
            <p style={{ margin: "0 0 8px", fontWeight: 700 }}>{L("١ — أضف الحساب لتطبيق المصادقة:", "1 — Add the account to your authenticator app:")}</p>
            <p style={{ margin: "0 0 4px" }}>{L("المفتاح اليدوي:", "Manual key:")}</p>
            <bdi className="num" style={{ display: "block", fontWeight: 800, fontSize: 15, letterSpacing: 1, wordBreak: "break-all", background: "#fff", border: "1px solid #c7d1e0", borderRadius: 8, padding: "8px 10px" }}>
              {setup.secret}
            </bdi>
            <p style={{ margin: "10px 0 4px" }}>{L("أو رابط otpauth (انسخه في التطبيق):", "Or the otpauth link (paste into the app):")}</p>
            <bdi style={{ display: "block", fontSize: 11.5, color: "#5c7096", wordBreak: "break-all" }}>{setup.otpauth_uri}</bdi>
          </div>
          <form style={{ marginTop: 12 }} onSubmit={(event) => { event.preventDefault(); void enable(); }}>
            <Field label={L("٢ — أدخل أول رمز يظهر في التطبيق", "2 — Enter the first code shown in the app")} ltr
              placeholder="123456" value={code} onChange={(event) => setCode(event.target.value)}
              required minLength={6} maxLength={8} autoComplete="one-time-code" />
            <button type="submit" className="btn" style={{ marginTop: 8 }} disabled={busy}>
              {busy ? <span className="spinner" /> : null} {L("تحقق وفعّل", "Verify & enable")}
            </button>
          </form>
        </>
      )}

      {recoveryCodes !== null ? (
        <div className="danger" style={{ borderInlineStart: "4px solid #a33636", background: "#fbeaea", borderRadius: 8, padding: "12px 16px", marginTop: 14 }}>
          <p style={{ fontWeight: 800, margin: "0 0 8px", color: "#a33636" }}>
            {L("رموز الاسترداد — تُعرض مرة واحدة فقط. احفظها في مكان آمن:", "Recovery codes — shown only once. Store them somewhere safe:")}
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 6 }}>
            {recoveryCodes.map((rc) => (
              <bdi key={rc} className="num" style={{ background: "#fff", border: "1px solid #F2C4C4", borderRadius: 6, padding: "4px 8px", fontWeight: 700 }}>{rc}</bdi>
            ))}
          </div>
          <button className="btn-secondary" style={{ marginTop: 10 }} onClick={() => {
            void navigator.clipboard?.writeText(recoveryCodes.join("\n"));
            toast(L("نُسخت الرموز", "Codes copied"));
          }}>{L("نسخ الكل", "Copy all")}</button>
        </div>
      ) : null}
    </div>
  );
}

function PasswordCard() {
  const toast = useToast();
  const { L, lang } = useLang();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);

  const change = async () => {
    setBusy(true);
    try {
      await saApi("/me/password", { method: "PATCH", body: { current_password: current, new_password: next } });
      setCurrent("");
      setNext("");
      toast(L("غُيّرت كلمة المرور", "Password changed"));
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card" style={{ padding: 18, marginTop: 14 }}>
      <h2 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 10px" }}>{L("تغيير كلمة المرور", "Change password")}</h2>
      <form onSubmit={(event) => { event.preventDefault(); void change(); }} style={{ maxWidth: 420 }}>
        <Field label={L("كلمة المرور الحالية", "Current password")} ltr type="password" value={current}
          autoComplete="current-password" onChange={(event) => setCurrent(event.target.value)} required />
        <Field label={L("كلمة المرور الجديدة (10 أحرف فأكثر)", "New password (10+ characters)")} ltr type="password" value={next}
          autoComplete="new-password" minLength={10} onChange={(event) => setNext(event.target.value)} required />
        <button type="submit" className="btn" style={{ marginTop: 10 }} disabled={busy}>
          {busy ? <span className="spinner" /> : null} {L("حفظ", "Save")}
        </button>
      </form>
    </div>
  );
}

export default function SaSecurityPage() {
  const { L } = useLang();
  return (
    <SaShell title={L("الأمان", "Security")}>
      <main className="page-wrap narrow">
        <TwoFactorCard />
        <PasswordCard />
        <p style={{ fontSize: 12.5, color: "#5c7096", margin: "12px 0 0" }}>
          {L("الإجراءات الحسّاسة (تغيير تكلفة الدكتور، تعليق منشأة، إدارة حسابات المنصة) تطلب رمز مصادقة حياً إضافياً عند تفعيل 2FA (DOC-20 §١.٣).",
             "Sensitive actions (doctor-price change, facility suspension, platform account management) require an extra live code once 2FA is enabled (DOC-20 §1.3).")}
        </p>
      </main>
    </SaShell>
  );
}
