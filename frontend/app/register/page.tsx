"use client";

/** الصفحة 2 — تسجيل منشأة جديدة W-002: معالج 3 خطوات (بيانات، أدمن، عدد الدكاترة) — FR-101.
 *  الاشتراك بعدد الدكاترة فقط، والتكلفة من كتالوج السوبر أدمن (تعديل مالك DOC-20 §٠.١). */

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { LangToggle, useLang } from "@/lib/i18n";
import { Logo } from "@/components/Shell";
import { Field, SpecBadge, ToastProvider, useToast } from "@/components/ui";

interface PublicPlan {
  code: string;
  name_ar: string;
  name_en: string;
  doctor_price_sar: string;
  billing_cycle: "monthly" | "yearly";
}

const STEP_LABELS: readonly { ar: string; en: string }[] = [
  { ar: "بيانات المنشأة", en: "Facility details" },
  { ar: "حساب الأدمن", en: "Admin account" },
  { ar: "عدد الدكاترة", en: "Doctors count" },
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
            {index > 0 ? <div style={{ width: 56, height: 2, background: number <= step ? "#12a594" : "#c7d1e0", marginTop: 16 }} /> : null}
            <div style={{ textAlign: "center", width: 110 }}>
              <div style={{
                width: 34, height: 34, borderRadius: 999, display: "inline-flex", alignItems: "center", justifyContent: "center",
                fontWeight: 700, fontSize: 14,
                background: done ? "#12a594" : current ? "#00736d" : "#fff",
                color: done || current ? "#fff" : "#5c7096",
                border: done ? "2px solid #12a594" : current ? "2px solid #00736d" : "2px solid #c7d1e0",
              }}>{done ? "✓" : <span className="num">{number}</span>}</div>
              <div style={{ fontSize: 12.5, marginTop: 4, color: current ? "#005a55" : "#5c7096", fontWeight: current ? 700 : 400 }}>{L(label.ar, label.en)}</div>
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
  const [plans, setPlans] = useState<PublicPlan[]>([]);
  const [planCode, setPlanCode] = useState("monthly");

  // تكلفة الدكتور من كتالوج السوبر أدمن — لا أسعار مثبّتة في الواجهة (DOC-20 §٠.١)
  useEffect(() => {
    void (async () => {
      try {
        const body = await api<PublicPlan[]>("/plans");
        setPlans(body.data);
        if (body.data.length > 0 && !body.data.some((p) => p.code === "monthly")) {
          setPlanCode(body.data[0]!.code);
        }
      } catch { /* تُعرض البطاقات فارغة والتسجيل يستخدم monthly الافتراضي */ }
    })();
  }, []);

  const selectedPlan = plans.find((p) => p.code === planCode);
  const unit = selectedPlan ? Number(selectedPlan.doctor_price_sar) : 0;
  const subtotal = seats * unit;
  const vat = subtotal * 0.15;

  const clampSeats = (value: number) => Math.min(500, Math.max(1, Math.round(value)));

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
          plan: planCode,
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
      <p style={{ color: "#5c7096", fontSize: 14, margin: 0 }}>
        {L("الاشتراك بعدد الدكاترة — تحدد العدد الآن وتوسّعه أو تقلّصه لاحقاً.",
           "Subscription by doctor count — set the number now, expand or reduce it later.")}
      </p>

      <div className="card pad24" style={{ width: "min(620px,94vw)", marginTop: 16 }}>
        {done ? (
          <div style={{ textAlign: "center" }}>
            <div style={{ width: 56, height: 56, borderRadius: 999, background: "#e6f7f4", display: "inline-flex", alignItems: "center", justifyContent: "center", color: "#12a594", fontSize: 24, fontWeight: 800 }}>✓</div>
            <h2 style={{ fontSize: 18, fontWeight: 700, color: "#005a55", margin: "12px 0 6px" }}>{L("أُنشئت المنشأة بنجاح", "Facility created successfully")}</h2>
            <p style={{ fontSize: 14, color: "#5c7096" }}>
              {L("حُجز اشتراك", "Reserved a subscription for")} <span className="num">{seats}</span> {L("دكتوراً، وأُنشئ حساب الأدمن. الخطوة التالية: الدخول ثم إنشاء العيادات وحسابات الدكاترة.",
                "doctors and created the admin account. Next: sign in, then create clinics and doctor accounts.")}
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
                <p style={{ fontSize: 12.5, color: "#5c7096", margin: "8px 0 0" }}>
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
                <p style={{ fontSize: 12.5, color: "#5c7096", margin: "8px 0 0" }}>
                  {L("اسم المستخدم فريد داخل المنشأة، والتخزين بـ", "The username is unique within the facility; passwords are stored with ")}<bdi>argon2id</bdi>.
                </p>
              </>
            ) : null}
            {step === 3 ? (
              <>
                <label className="field-label" htmlFor="doctors-count">{L("كم دكتوراً تحتاج؟ (اكتب العدد أو استخدم العدّاد)", "How many doctors do you need? (type or use the counter)")}</label>
                <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
                  <button type="button" aria-label={L("إنقاص", "Decrease")} onClick={() => setSeats((value) => clampSeats(value - 1))}
                    style={{ width: 44, height: 44, border: "1.5px solid #00736d", borderRadius: 10, background: "#fff", color: "#005a55", fontSize: 18, fontWeight: 700, cursor: "pointer" }}>−</button>
                  <input id="doctors-count" className="field num" type="number" min={1} max={500} value={seats} dir="ltr"
                    style={{ margin: 0, width: 96, textAlign: "center", fontSize: 24, fontWeight: 800, color: "#005a55", height: 44 }}
                    onChange={(event) => setSeats(clampSeats(Number(event.target.value) || 1))} />
                  <button type="button" aria-label={L("زيادة", "Increase")} onClick={() => setSeats((value) => clampSeats(value + 1))}
                    style={{ width: 44, height: 44, border: "1.5px solid #00736d", borderRadius: 10, background: "#fff", color: "#005a55", fontSize: 18, fontWeight: 700, cursor: "pointer" }}>+</button>
                  <span style={{ fontSize: 12.5, color: "#5c7096" }}>{L("كل دكتور نشط يستهلك اشتراكاً (FR-202)", "Each active doctor consumes one subscription (FR-202)")}</span>
                </div>
                <label className="field-label">{L("دورة الفوترة", "Billing cycle")}</label>
                {plans.length === 0 ? (
                  <div className="grid-empty">{L("جارٍ تحميل التسعير…", "Loading pricing…")}</div>
                ) : (
                  <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.min(plans.length, 2)}, 1fr)`, gap: 10 }}>
                    {plans.map((p) => (
                      <button key={p.code} type="button" className={planCode === p.code ? "select-card selected" : "select-card"}
                        style={planCode === p.code ? { background: "#d6f5f2" } : undefined} onClick={() => setPlanCode(p.code)}>
                        <strong>{lang === "ar" ? p.name_ar : p.name_en}</strong>
                        <div style={{ fontSize: 12.5, color: "#5c7096", marginTop: 4 }}>
                          <span className="num">{fmt(Number(p.doctor_price_sar))}</span>{" "}
                          {p.billing_cycle === "yearly" ? L("ر.س / دكتور / سنة", "SAR / doctor / year") : L("ر.س / دكتور / شهر", "SAR / doctor / month")}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
                <div className="sub-box" style={{ marginTop: 14, fontSize: 14 }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span><span className="num">{seats}</span> {L("دكتور ×", "doctors ×")} <span className="num">{fmt(unit)}</span></span>
                    <bdi>{fmt(subtotal)} {L("ر.س", "SAR")}</bdi>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
                    <span>{L("ضريبة القيمة المضافة 15% — تُعرض مفصولة", "VAT 15% — shown separately")}</span>
                    <bdi>{fmt(vat)} {L("ر.س", "SAR")}</bdi>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, fontWeight: 700 }}>
                    <span>{L("الإجمالي", "Total")}</span>
                    <bdi>{fmt(subtotal + vat)} {L("ر.س", "SAR")}</bdi>
                  </div>
                </div>
                <div className="info-box" style={{ marginTop: 12 }}>
                  {L("الاشتراك بعدد الدكاترة فقط — التكلفة يحددها مالك المنصة وتظهر هنا لحظياً، وتقدر توسّع أو تقلّص العدد لاحقاً من لوحة الأدمن.",
                     "Subscription is by doctor count only — pricing is set by the platform owner and shown here live; you can expand or reduce the count later from the admin panel.")}
                </div>
              </>
            ) : null}

            {error !== null ? <p style={{ color: "#d94b4b", fontSize: 12.5, fontWeight: 700, margin: "12px 0 0" }}>{error}</p> : null}

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
