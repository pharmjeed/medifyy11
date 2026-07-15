"use client";

/** الصفحة 2 — تسجيل منشأة جديدة W-002: معالج 3 خطوات (بيانات، أدمن، مقاعد) — FR-101 — ثنائية اللغة (D-30). */

import Link from "next/link";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { LangToggle, useLang } from "@/lib/i18n";
import { Logo } from "@/components/Shell";
import { Field, SpecBadge, ToastProvider, useToast } from "@/components/ui";

const MONTHLY = 499;
const YEARLY = 5388;

const STEP_LABELS: readonly { ar: string; en: string }[] = [
  { ar: "بيانات المنشأة", en: "Facility details" },
  { ar: "حساب الأدمن", en: "Admin account" },
  { ar: "المقاعد والخطة", en: "Seats & plan" },
];

function fmt(value: number): string {
  return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function Stepper({ step }: { step: number }) {
  const { L } = useLang();
  return (
    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "center", gap: 0, margin: "18px 0 22px" }}>
      {STEP_LABELS.map((label, index) => {
        const number = index + 1;
        const done = number < step;
        const current = number === step;
        return (
          <div key={label.ar} style={{ display: "flex", alignItems: "center" }}>
            {index > 0 ? <div style={{ width: 56, height: 2, background: number <= step ? "#2E9E5B" : "#D7E3E8", marginTop: 16 }} /> : null}
            <div style={{ textAlign: "center", width: 110 }}>
              <div style={{
                width: 34, height: 34, borderRadius: 999, display: "inline-flex", alignItems: "center", justifyContent: "center",
                fontWeight: 700, fontSize: 14,
                background: done ? "#2E9E5B" : current ? "#0E7C86" : "#fff",
                color: done || current ? "#fff" : "#5B7280",
                border: done ? "2px solid #2E9E5B" : current ? "2px solid #0E7C86" : "2px solid #D7E3E8",
              }}>{done ? "✓" : <span className="num">{number}</span>}</div>
              <div style={{ fontSize: 12.5, marginTop: 4, color: current ? "#0A5C64" : "#5B7280", fontWeight: current ? 700 : 400 }}>{L(label.ar, label.en)}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RegisterInner() {
  const toast = useToast();
  const { L, lang } = useLang();
  const [step, setStep] = useState(1);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [commercialReg, setCommercialReg] = useState("");
  const [adminName, setAdminName] = useState("");
  const [adminUsername, setAdminUsername] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [seats, setSeats] = useState(3);
  const [plan, setPlan] = useState<"yearly" | "monthly">("yearly");

  const unit = plan === "yearly" ? YEARLY : MONTHLY;
  const subtotal = seats * unit;
  const vat = subtotal * 0.15;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api("/facilities/register", {
        method: "POST",
        body: {
          name,
          commercial_reg: commercialReg,
          admin: { full_name: adminName, username: adminUsername, email: adminEmail, password: adminPassword },
          seats,
        },
      });
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? `${err.text(lang)} (${err.code})` : L("تعذر الاتصال بالخادم", "Could not reach the server"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main style={{ minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", padding: "40px 20px" }}>
      <LangToggle floating />
      <Logo />
      <h1 style={{ fontSize: 22, fontWeight: 800, margin: "14px 0 4px", display: "flex", gap: 8, alignItems: "center" }}>
        {L("تسجيل منشأة جديدة", "Register a new facility")} <SpecBadge id="W-002" />
      </h1>
      <p style={{ color: "#5B7280", fontSize: 14, margin: 0 }}>
        {L("الاشتراك بالمقعد لكل دكتور — يحدده الأدمن الآن ويوسّعه لاحقاً.",
           "Per-seat subscription for each doctor — set by the admin now, expandable later.")}
      </p>

      <div className="card pad24" style={{ width: "min(620px,94vw)", marginTop: 16 }}>
        {done ? (
          <div style={{ textAlign: "center" }}>
            <div style={{ width: 56, height: 56, borderRadius: 999, background: "#E8F6EE", display: "inline-flex", alignItems: "center", justifyContent: "center", color: "#2E9E5B", fontSize: 24, fontWeight: 800 }}>✓</div>
            <h2 style={{ fontSize: 18, fontWeight: 700, color: "#0A5C64", margin: "12px 0 6px" }}>{L("أُنشئت المنشأة بنجاح", "Facility created successfully")}</h2>
            <p style={{ fontSize: 14, color: "#5B7280" }}>
              {L("حُجزت", "Reserved")} <span className="num">{seats}</span> {L("مقاعد، وأُنشئ حساب الأدمن. الخطوة التالية: الدخول ثم إنشاء العيادات وحسابات الدكاترة.",
                "seats and created the admin account. Next: sign in, then create clinics and doctor accounts.")}
            </p>
            <Link href="/login" className="btn big" style={{ textDecoration: "none", display: "inline-flex", marginTop: 8 }}>{L("الذهاب للدخول", "Go to sign in")}</Link>
          </div>
        ) : (
          <>
            <Stepper step={step} />
            {step === 1 ? (
              <>
                <Field label={L("اسم المنشأة", "Facility name")} placeholder={L("مثال: مجمع الشفاء الطبي", "e.g. Al-Shifa Medical Complex")} value={name} onChange={(event) => setName(event.target.value)} />
                <Field label={L("رقم السجل التجاري", "Commercial registration number")} ltr placeholder="1010XXXXXX" value={commercialReg} onChange={(event) => setCommercialReg(event.target.value)} />
                <p style={{ fontSize: 12.5, color: "#5B7280", margin: "8px 0 0" }}>
                  {L("السجل فريد على مستوى النظام", "The registration number is unique system-wide")} (<bdi>commercial_reg unique</bdi>).
                </p>
              </>
            ) : null}
            {step === 2 ? (
              <>
                <Field label={L("اسم الأدمن الكامل", "Admin full name")} placeholder={L("مثال: سلطان عبدالله الحربي", "e.g. Sultan Abdullah Alharbi")} value={adminName} onChange={(event) => setAdminName(event.target.value)} />
                <Field label={L("اسم المستخدم", "Username")} ltr placeholder="admin.username" value={adminUsername} onChange={(event) => setAdminUsername(event.target.value)} />
                <Field label={L("بريد الأدمن (قناة استعادة كلمة المرور)", "Admin email (password recovery channel)")} ltr type="email" placeholder="admin@facility.sa" value={adminEmail} onChange={(event) => setAdminEmail(event.target.value)} />
                <Field label={L("كلمة المرور", "Password")} ltr type="password" placeholder="••••••••" value={adminPassword} onChange={(event) => setAdminPassword(event.target.value)} />
                <p style={{ fontSize: 12.5, color: "#5B7280", margin: "8px 0 0" }}>
                  {L("اسم المستخدم فريد داخل المنشأة، والتخزين بـ", "The username is unique within the facility; passwords are stored with ")}<bdi>argon2id</bdi>.
                </p>
              </>
            ) : null}
            {step === 3 ? (
              <>
                <label className="field-label">{L("عدد مقاعد الدكاترة الأولي", "Initial doctor seat count")}</label>
                <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                  <button type="button" aria-label={L("إنقاص", "Decrease")} onClick={() => setSeats((value) => Math.max(1, value - 1))}
                    style={{ width: 44, height: 44, border: "1.5px solid #0E7C86", borderRadius: 10, background: "#fff", color: "#0A5C64", fontSize: 18, fontWeight: 700, cursor: "pointer" }}>−</button>
                  <span className="num" style={{ fontSize: 28, fontWeight: 800, color: "#0A5C64", minWidth: 40, textAlign: "center" }}>{seats}</span>
                  <button type="button" aria-label={L("زيادة", "Increase")} onClick={() => setSeats((value) => Math.min(50, value + 1))}
                    style={{ width: 44, height: 44, border: "1.5px solid #0E7C86", borderRadius: 10, background: "#fff", color: "#0A5C64", fontSize: 18, fontWeight: 700, cursor: "pointer" }}>+</button>
                  <span style={{ fontSize: 12.5, color: "#5B7280" }}>{L("كل دكتور نشط يستهلك مقعداً (FR-202)", "Each active doctor consumes a seat (FR-202)")}</span>
                </div>
                <label className="field-label">{L("الخطة", "Plan")}</label>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  <button type="button" className={plan === "yearly" ? "select-card selected" : "select-card"}
                    style={plan === "yearly" ? { background: "#EAF6F7" } : undefined} onClick={() => setPlan("yearly")}>
                    <strong>{L("سنوية", "Yearly")}</strong> <span className="badge success">{L("وفر 10%", "Save 10%")}</span>
                    <div style={{ fontSize: 12.5, color: "#5B7280", marginTop: 4 }}><span className="num">5,388</span> {L("ر.س / مقعد / سنة", "SAR / seat / year")}</div>
                  </button>
                  <button type="button" className={plan === "monthly" ? "select-card selected" : "select-card"}
                    style={plan === "monthly" ? { background: "#EAF6F7" } : undefined} onClick={() => setPlan("monthly")}>
                    <strong>{L("شهرية", "Monthly")}</strong>
                    <div style={{ fontSize: 12.5, color: "#5B7280", marginTop: 4 }}><span className="num">499</span> {L("ر.س / مقعد / شهر", "SAR / seat / month")}</div>
                  </button>
                </div>
                <div className="sub-box" style={{ marginTop: 14, fontSize: 14 }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span><span className="num">{seats}</span> {L("مقاعد ×", "seats ×")} <span className="num">{fmt(unit)}</span> ({plan === "yearly" ? L("سنوي", "yearly") : L("شهري", "monthly")})</span>
                    <bdi>{fmt(subtotal)} SAR</bdi>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
                    <span>{L("ضريبة القيمة المضافة 15% — تُعرض مفصولة", "VAT 15% — shown separately")}</span>
                    <bdi>{fmt(vat)} SAR</bdi>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, fontWeight: 700 }}>
                    <span>{L("الإجمالي", "Total")}</span>
                    <bdi>{fmt(subtotal + vat)} SAR</bdi>
                  </div>
                </div>
                <div className="info-box" style={{ marginTop: 12 }}>
                  <strong>{L("تجربة 30 يوماً", "30-day trial")}</strong> — {L("متاحة للمنشآت الجديدة بحد 3 مقاعد — تخدم بروتوكول العيادة التجريبية. الأسعار توضيحية وتُقفل وفق DOC-09 §٤.",
                    "Available to new facilities with up to 3 seats — serves the pilot clinic protocol. Prices are illustrative and locked per DOC-09 §4.")}
                </div>
              </>
            ) : null}

            {error !== null ? <p style={{ color: "#C0392B", fontSize: 12.5, fontWeight: 700, margin: "12px 0 0" }}>{error}</p> : null}

            <div className="modal-actions">
              {step > 1 ? <button className="btn-secondary" onClick={() => setStep((value) => value - 1)}>{L("السابق", "Back")}</button> : null}
              {step < 3 ? (
                <button className="btn" onClick={() => {
                  if (step === 1 && (name.trim().length < 2 || commercialReg.trim().length < 4)) { toast(L("أكمل بيانات المنشأة أولاً", "Complete the facility details first")); return; }
                  if (step === 2 && (adminName.trim().length < 2 || adminUsername.trim().length < 3 || !adminEmail.includes("@") || adminPassword.length < 8)) {
                    toast(L("أكمل حساب الأدمن — كلمة المرور 8 أحرف فأكثر وبريد صالح", "Complete the admin account — password of 8+ characters and a valid email"));
                    return;
                  }
                  setStep((value) => value + 1);
                }}>{L("التالي", "Next")}</button>
              ) : (
                <button className="btn-success big" onClick={() => void submit()} disabled={busy}>
                  {busy ? <span className="spinner" /> : null} {L("إنشاء المنشأة", "Create facility")}
                </button>
              )}
              <span style={{ flex: 1 }} />
              <Link href="/login" className="btn-ghost">{L("العودة للدخول", "Back to sign in")}</Link>
            </div>
          </>
        )}
      </div>
    </main>
  );
}

export default function RegisterPage() {
  return (
    <ToastProvider>
      <RegisterInner />
    </ToastProvider>
  );
}
