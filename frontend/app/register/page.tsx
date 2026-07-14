"use client";

/** الصفحة 2 — تسجيل منشأة جديدة W-002: معالج 3 خطوات (بيانات، أدمن، مقاعد) — FR-101. */

import Link from "next/link";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { Logo } from "@/components/Shell";
import { Field, SpecBadge, ToastProvider, useToast } from "@/components/ui";

const MONTHLY = 499;
const YEARLY = 5388;

function fmt(value: number): string {
  return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function Stepper({ step }: { step: number }) {
  const labels = ["بيانات المنشأة", "حساب الأدمن", "المقاعد والخطة"];
  return (
    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "center", gap: 0, margin: "18px 0 22px" }}>
      {labels.map((label, index) => {
        const number = index + 1;
        const done = number < step;
        const current = number === step;
        return (
          <div key={label} style={{ display: "flex", alignItems: "center" }}>
            {index > 0 ? <div style={{ width: 56, height: 2, background: number <= step ? "#2E9E5B" : "#D7E3E8", marginTop: 16 }} /> : null}
            <div style={{ textAlign: "center", width: 110 }}>
              <div style={{
                width: 34, height: 34, borderRadius: 999, display: "inline-flex", alignItems: "center", justifyContent: "center",
                fontWeight: 700, fontSize: 14,
                background: done ? "#2E9E5B" : current ? "#0E7C86" : "#fff",
                color: done || current ? "#fff" : "#5B7280",
                border: done ? "2px solid #2E9E5B" : current ? "2px solid #0E7C86" : "2px solid #D7E3E8",
              }}>{done ? "✓" : <span className="num">{number}</span>}</div>
              <div style={{ fontSize: 12.5, marginTop: 4, color: current ? "#0A5C64" : "#5B7280", fontWeight: current ? 700 : 400 }}>{label}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RegisterInner() {
  const toast = useToast();
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
      setError(err instanceof ApiError ? `${err.messageAr} (${err.code})` : "تعذر الاتصال بالخادم");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main style={{ minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", padding: "40px 20px" }}>
      <Logo />
      <h1 style={{ fontSize: 22, fontWeight: 800, margin: "14px 0 4px", display: "flex", gap: 8, alignItems: "center" }}>
        تسجيل منشأة جديدة <SpecBadge id="W-002" />
      </h1>
      <p style={{ color: "#5B7280", fontSize: 14, margin: 0 }}>الاشتراك بالمقعد لكل دكتور — يحدده الأدمن الآن ويوسّعه لاحقاً.</p>

      <div className="card pad24" style={{ width: "min(620px,94vw)", marginTop: 16 }}>
        {done ? (
          <div style={{ textAlign: "center" }}>
            <div style={{ width: 56, height: 56, borderRadius: 999, background: "#E8F6EE", display: "inline-flex", alignItems: "center", justifyContent: "center", color: "#2E9E5B", fontSize: 24, fontWeight: 800 }}>✓</div>
            <h2 style={{ fontSize: 18, fontWeight: 700, color: "#0A5C64", margin: "12px 0 6px" }}>أُنشئت المنشأة بنجاح</h2>
            <p style={{ fontSize: 14, color: "#5B7280" }}>
              حُجزت <span className="num">{seats}</span> مقاعد، وأُنشئ حساب الأدمن. الخطوة التالية: الدخول ثم إنشاء العيادات وحسابات الدكاترة.
            </p>
            <Link href="/login" className="btn big" style={{ textDecoration: "none", display: "inline-flex", marginTop: 8 }}>الذهاب للدخول</Link>
          </div>
        ) : (
          <>
            <Stepper step={step} />
            {step === 1 ? (
              <>
                <Field label="اسم المنشأة" placeholder="مثال: مجمع الشفاء الطبي" value={name} onChange={(event) => setName(event.target.value)} />
                <Field label="رقم السجل التجاري" ltr placeholder="1010XXXXXX" value={commercialReg} onChange={(event) => setCommercialReg(event.target.value)} />
                <p style={{ fontSize: 12.5, color: "#5B7280", margin: "8px 0 0" }}>السجل فريد على مستوى النظام (<bdi>commercial_reg unique</bdi>).</p>
              </>
            ) : null}
            {step === 2 ? (
              <>
                <Field label="اسم الأدمن الكامل" placeholder="مثال: سلطان عبدالله الحربي" value={adminName} onChange={(event) => setAdminName(event.target.value)} />
                <Field label="اسم المستخدم" ltr placeholder="admin.username" value={adminUsername} onChange={(event) => setAdminUsername(event.target.value)} />
                <Field label="بريد الأدمن (قناة استعادة كلمة المرور)" ltr type="email" placeholder="admin@facility.sa" value={adminEmail} onChange={(event) => setAdminEmail(event.target.value)} />
                <Field label="كلمة المرور" ltr type="password" placeholder="••••••••" value={adminPassword} onChange={(event) => setAdminPassword(event.target.value)} />
                <p style={{ fontSize: 12.5, color: "#5B7280", margin: "8px 0 0" }}>اسم المستخدم فريد داخل المنشأة، والتخزين بـ<bdi>argon2id</bdi>.</p>
              </>
            ) : null}
            {step === 3 ? (
              <>
                <label className="field-label">عدد مقاعد الدكاترة الأولي</label>
                <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                  <button type="button" aria-label="إنقاص" onClick={() => setSeats((value) => Math.max(1, value - 1))}
                    style={{ width: 44, height: 44, border: "1.5px solid #0E7C86", borderRadius: 10, background: "#fff", color: "#0A5C64", fontSize: 18, fontWeight: 700, cursor: "pointer" }}>−</button>
                  <span className="num" style={{ fontSize: 28, fontWeight: 800, color: "#0A5C64", minWidth: 40, textAlign: "center" }}>{seats}</span>
                  <button type="button" aria-label="زيادة" onClick={() => setSeats((value) => Math.min(50, value + 1))}
                    style={{ width: 44, height: 44, border: "1.5px solid #0E7C86", borderRadius: 10, background: "#fff", color: "#0A5C64", fontSize: 18, fontWeight: 700, cursor: "pointer" }}>+</button>
                  <span style={{ fontSize: 12.5, color: "#5B7280" }}>كل دكتور نشط يستهلك مقعداً (FR-202)</span>
                </div>
                <label className="field-label">الخطة</label>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  <button type="button" className={plan === "yearly" ? "select-card selected" : "select-card"}
                    style={plan === "yearly" ? { background: "#EAF6F7" } : undefined} onClick={() => setPlan("yearly")}>
                    <strong>سنوية</strong> <span className="badge success">وفر 10%</span>
                    <div style={{ fontSize: 12.5, color: "#5B7280", marginTop: 4 }}><span className="num">5,388</span> ر.س / مقعد / سنة</div>
                  </button>
                  <button type="button" className={plan === "monthly" ? "select-card selected" : "select-card"}
                    style={plan === "monthly" ? { background: "#EAF6F7" } : undefined} onClick={() => setPlan("monthly")}>
                    <strong>شهرية</strong>
                    <div style={{ fontSize: 12.5, color: "#5B7280", marginTop: 4 }}><span className="num">499</span> ر.س / مقعد / شهر</div>
                  </button>
                </div>
                <div className="sub-box" style={{ marginTop: 14, fontSize: 14 }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span><span className="num">{seats}</span> مقاعد × <span className="num">{fmt(unit)}</span> ({plan === "yearly" ? "سنوي" : "شهري"})</span>
                    <bdi>{fmt(subtotal)} SAR</bdi>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
                    <span>ضريبة القيمة المضافة 15% — تُعرض مفصولة</span>
                    <bdi>{fmt(vat)} SAR</bdi>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, fontWeight: 700 }}>
                    <span>الإجمالي</span>
                    <bdi>{fmt(subtotal + vat)} SAR</bdi>
                  </div>
                </div>
                <div className="info-box" style={{ marginTop: 12 }}>
                  <strong>تجربة 30 يوماً</strong> — متاحة للمنشآت الجديدة بحد 3 مقاعد — تخدم بروتوكول العيادة التجريبية. الأسعار توضيحية وتُقفل وفق DOC-09 §٤.
                </div>
              </>
            ) : null}

            {error !== null ? <p style={{ color: "#C0392B", fontSize: 12.5, fontWeight: 700, margin: "12px 0 0" }}>{error}</p> : null}

            <div className="modal-actions">
              {step > 1 ? <button className="btn-secondary" onClick={() => setStep((value) => value - 1)}>السابق</button> : null}
              {step < 3 ? (
                <button className="btn" onClick={() => {
                  if (step === 1 && (name.trim().length < 2 || commercialReg.trim().length < 4)) { toast("أكمل بيانات المنشأة أولاً"); return; }
                  if (step === 2 && (adminName.trim().length < 2 || adminUsername.trim().length < 3 || !adminEmail.includes("@") || adminPassword.length < 8)) {
                    toast("أكمل حساب الأدمن — كلمة المرور 8 أحرف فأكثر وبريد صالح");
                    return;
                  }
                  setStep((value) => value + 1);
                }}>التالي</button>
              ) : (
                <button className="btn-success big" onClick={() => void submit()} disabled={busy}>
                  {busy ? <span className="spinner" /> : null} إنشاء المنشأة
                </button>
              )}
              <span style={{ flex: 1 }} />
              <Link href="/login" className="btn-ghost">العودة للدخول</Link>
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
