"use client";

/** إدارة منشأة من المنصة — الحالة والاشتراك والمستخدمون والفواتير في صفحة واحدة.
 *  كل فعل هنا يُدوَّن في سجل تدقيق المنشأة (actor=NULL + meta.sa). */

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { SaShell } from "@/components/SaShell";
import { Field, Modal, Tabs, fmtDateTime, useToast } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import type { Lang } from "@/lib/i18n";
import { saApi } from "@/lib/sa";
import type { SaApiOptions } from "@/lib/sa";
import type { FacilityStatus, SaFacilityDetail, SaFacilityUser, SaInvoice, SaPlan } from "@/lib/types";

type LFn = (ar: string, en: string) => string;

/** نداء حسّاس: عند طلب الخادم إعادة مصادقة (2FA مفعّل) يسأل عن رمز حي ويعيد المحاولة مرة واحدة. */
async function saSensitive<T>(L: LFn, path: string, options: SaApiOptions) {
  try {
    return await saApi<T>(path, options);
  } catch (err) {
    if (err instanceof ApiError && err.code === "MDF-4015" && err.details["reason"] === "reauth_required") {
      const code = window.prompt(L("إجراء حسّاس — أدخل رمز المصادقة الحالي:", "Sensitive action — enter your current authenticator code:"));
      if (code) return await saApi<T>(path, { ...options, reauthCode: code });
    }
    throw err;
  }
}

const FACILITY_STATUS_META: Record<FacilityStatus, { ar: string; en: string; cls: string }> = {
  active: { ar: "نشطة", en: "Active", cls: "badge success" },
  suspended: { ar: "معلّقة", en: "Suspended", cls: "badge warn" },
  archived: { ar: "مؤرشفة", en: "Archived", cls: "badge neutral" },
};

const INVOICE_STATUS: Record<SaInvoice["status"], { ar: string; en: string; cls: string }> = {
  paid: { ar: "مسددة", en: "Paid", cls: "badge success" },
  due: { ar: "مستحقة", en: "Due", cls: "badge warn" },
  overdue: { ar: "متأخرة", en: "Overdue", cls: "badge danger" },
  void: { ar: "ملغاة", en: "Void", cls: "badge neutral" },
};

const SEAT_REASON: Record<string, { ar: string; en: string }> = {
  expand: { ar: "توسعة", en: "Expansion" },
  reduce: { ar: "تقليص", en: "Reduction" },
  activate_dr: { ar: "تفعيل دكتور", en: "Doctor activated" },
  deactivate_dr: { ar: "تعطيل دكتور", en: "Doctor deactivated" },
};

function fmtSar(value: string): string {
  const num = Number(value);
  if (Number.isNaN(num)) return value;
  return num.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function apiErrorText(err: unknown, lang: Lang, L: LFn): string {
  return err instanceof ApiError ? `${err.text(lang)} (${err.code})` : L("تعذر الاتصال بالخادم", "Could not reach the server");
}

/* ===== بطاقة الحالة والاشتراك ===== */
function StatusSubscriptionTab({ detail, plans, reload }: {
  detail: SaFacilityDetail;
  plans: SaPlan[];
  reload: () => Promise<void>;
}) {
  const toast = useToast();
  const { L, lang } = useLang();
  const facility = detail.facility;
  const sub = detail.subscription;
  const [planCode, setPlanCode] = useState(sub?.plan ?? "");
  const [seats, setSeats] = useState(sub?.seats_total ?? 1);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setPlanCode(sub?.plan ?? "");
    setSeats(sub?.seats_total ?? 1);
  }, [sub?.plan, sub?.seats_total]);

  const setStatus = async (status: FacilityStatus) => {
    setBusy(true);
    try {
      await saSensitive(L, `/facilities/${facility.id}`, { method: "PATCH", body: { status } });
      toast(status === "active"
        ? L("فُعّلت المنشأة — يسري فوراً على دخول أدمنها ودكاترتها", "Facility activated — takes effect immediately for its admin and doctors")
        : L("حُدّثت حالة المنشأة — يُمنع دخول مستخدميها فوراً (MDF-4013)", "Facility status updated — its users are blocked immediately (MDF-4013)"));
      await reload();
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setBusy(false);
    }
  };

  const applySubscription = async () => {
    if (sub === null) return;
    const body: Record<string, unknown> = {};
    if (planCode !== sub.plan) body["plan_code"] = planCode;
    if (seats !== sub.seats_total) body["seats_total"] = seats;
    if (Object.keys(body).length === 0) {
      toast(L("لا تغيير في الاشتراك", "No subscription change"));
      return;
    }
    setBusy(true);
    try {
      await saApi(`/facilities/${facility.id}/subscription`, { method: "PATCH", body });
      toast(L("حُدّث الاشتراك — أصدر فاتورة من تبويب الفواتير إن لزم", "Subscription updated — issue an invoice from the invoices tab if needed"));
      await reload();
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setBusy(false);
    }
  };

  const stepBtn = {
    width: 36, height: 36, border: "1.5px solid #0E7C86", borderRadius: 10,
    background: "#fff", color: "#0A5C64", fontSize: 17, fontWeight: 700, cursor: "pointer",
  } as const;

  const meta = FACILITY_STATUS_META[facility.status];
  const selectedPlan = plans.find((plan) => plan.code === planCode);

  return (
    <>
      <div className="stat-grid">
        <div className="card" style={{ borderColor: "#C9A227" }}>
          <div className="stat-label">{L("حالة المنشأة", "Facility status")}</div>
          <div style={{ margin: "6px 0 10px" }}><span className={meta.cls}>{L(meta.ar, meta.en)}</span></div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {facility.status !== "active" ? (
              <button className="btn-row" disabled={busy} onClick={() => void setStatus("active")}>{L("تفعيل", "Activate")}</button>
            ) : null}
            {facility.status !== "suspended" ? (
              <button className="btn-row warn" disabled={busy} onClick={() => void setStatus("suspended")}>{L("تعليق", "Suspend")}</button>
            ) : null}
            {facility.status !== "archived" ? (
              <button className="btn-row danger" disabled={busy} onClick={() => {
                if (window.confirm(L("أرشفة المنشأة تمنع دخول كل مستخدميها — تأكيد؟", "Archiving blocks sign-in for all its users — confirm?"))) {
                  void setStatus("archived");
                }
              }}>{L("أرشفة", "Archive")}</button>
            ) : null}
          </div>
        </div>
        <div className="card">
          <div className="stat-label">{L("السجل التجاري", "Commercial registration")}</div>
          <div className="stat-value"><bdi className="num" style={{ fontSize: 20 }}>{facility.commercial_reg}</bdi></div>
          <div style={{ fontSize: 12.5, color: "#5B7280", marginTop: 4 }}>
            {L("سُجّلت:", "Registered:")} {fmtDateTime(facility.created_at)}
          </div>
        </div>
        <div className="card">
          <div className="stat-label">{L("دكاترة نشطون / عدد الدكاترة", "Active doctors / doctors count")}</div>
          <div className="stat-value num">{sub?.seats_used ?? 0} / {sub?.seats_total ?? 0}</div>
        </div>
        <div className="card">
          <div className="stat-label">{L("دورة الفوترة وتكلفة الدكتور", "Billing cycle & doctor cost")}</div>
          <div className="stat-value">{sub?.plan_info ? (lang === "ar" ? sub.plan_info.name_ar : sub.plan_info.name_en) : sub?.plan ?? "—"}</div>
          {sub?.plan_info ? (
            <div style={{ fontSize: 12.5, color: "#5B7280", marginTop: 4 }}>
              <bdi>{fmtSar(sub.plan_info.seat_price_sar)} SAR</bdi> {L("لكل دكتور /", "per doctor /")} {sub.plan_info.billing_cycle === "monthly" ? L("شهرياً", "month") : L("سنوياً", "year")}
            </div>
          ) : null}
        </div>
      </div>

      {sub !== null ? (
        <div className="card" style={{ marginTop: 14, padding: 18 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, margin: "0 0 12px" }}>{L("تعديل الاشتراك (فعل منصة)", "Edit subscription (platform action)")}</h3>
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "flex-end" }}>
            <div style={{ minWidth: 220 }}>
              <label className="field-label">{L("دورة الفوترة (تكلفة الدكتور)", "Billing cycle (doctor cost)")}</label>
              <select className="field" style={{ margin: 0 }} value={planCode} onChange={(event) => setPlanCode(event.target.value)}>
                {plans.filter((plan) => plan.is_active || plan.code === sub.plan).map((plan) => (
                  <option key={plan.code} value={plan.code}>
                    {(lang === "ar" ? plan.name_ar : plan.name_en)} — {fmtSar(plan.seat_price_sar)} SAR/{plan.billing_cycle === "monthly" ? L("شهر", "mo") : L("سنة", "yr")}{plan.is_active ? "" : L(" (موقوفة)", " (inactive)")}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="field-label">{L("عدد الدكاترة (كتابة أو عدّاد)", "Doctors count (type or counter)")}</label>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <button type="button" aria-label={L("إنقاص", "Decrease")} style={stepBtn} onClick={() => setSeats((value) => Math.max(1, Math.min(500, value - 1)))}>−</button>
                <input aria-label={L("عدد الدكاترة", "Doctors count")} className="field num" type="number" min={1} max={500} dir="ltr"
                  value={seats} style={{ margin: 0, width: 80, textAlign: "center", fontSize: 20, fontWeight: 800, color: "#0A5C64", height: 38 }}
                  onChange={(event) => setSeats(Math.min(500, Math.max(1, Math.round(Number(event.target.value) || 1))))} />
                <button type="button" aria-label={L("زيادة", "Increase")} style={stepBtn} onClick={() => setSeats((value) => Math.max(1, Math.min(500, value + 1)))}>+</button>
              </div>
            </div>
            <button className="btn h40" disabled={busy} onClick={() => void applySubscription()}>
              {busy ? <span className="spinner" /> : null} {L("تطبيق", "Apply")}
            </button>
            {selectedPlan ? (
              <div style={{ fontSize: 12.5, color: "#5B7280" }}>
                {L("تقدير الدورة حسب الدكاترة النشطين:", "Cycle estimate by active doctors:")}{" "}
                <bdi style={{ fontWeight: 700 }}>{fmtSar(String(Number(selectedPlan.seat_price_sar) * (sub.seats_used || 0)))} SAR</bdi> + {L("ضريبة 15%", "VAT 15%")}
              </div>
            ) : null}
          </div>
          <div className="info-box" style={{ marginTop: 12 }}>
            {L("تغيير الباقة/المقاعد من المنصة لا يُصدر فاتورة تلقائياً — الإصدار فعل صريح من تبويب الفواتير · التقليص لا ينزل عن المقاعد المستهلكة.",
               "Changing plan/seats from the platform does not auto-issue an invoice — issuing is an explicit action in the invoices tab · reduction cannot go below used seats.")}
          </div>
        </div>
      ) : null}

      <h3 style={{ fontSize: 15, fontWeight: 700, margin: "20px 0 10px" }}>{L("سجل أحداث المقاعد", "Seat events log")}</h3>
      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: "1fr 1.6fr .6fr .8fr" }}>
          <div>{L("الوقت", "Time")}</div><div>{L("الحدث", "Event")}</div><div>{L("التغير", "Change")}</div><div>{L("الفاعل", "Actor")}</div>
        </div>
        {detail.seat_events.length === 0 ? (
          <div className="grid-empty">{L("لا أحداث بعد", "No events yet")}</div>
        ) : (
          detail.seat_events.map((event, i) => {
            const reason = SEAT_REASON[event.reason];
            return (
              <div key={event.id} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: "1fr 1.6fr .6fr .8fr" }}>
                <div>{fmtDateTime(event.at)}</div>
                <div>{reason !== undefined ? L(reason.ar, reason.en) : event.reason}</div>
                <div className="num" style={{ fontWeight: 700, color: event.delta > 0 ? "#2E9E5B" : event.delta < 0 ? "#B07D10" : "#5B7280" }}>
                  {event.delta > 0 ? `+${event.delta}` : event.delta}
                </div>
                <div>
                  {event.by_platform
                    ? <span className="badge" style={{ background: "#C9A227", color: "#0F2233" }}>{L("المنصة", "Platform")}</span>
                    : <span className="badge neutral">{L("المنشأة", "Facility")}</span>}
                </div>
              </div>
            );
          })
        )}
      </div>
    </>
  );
}

/* ===== المستخدمون ===== */
function UsersTab({ detail, reload }: { detail: SaFacilityDetail; reload: () => Promise<void> }) {
  const toast = useToast();
  const { L, lang } = useLang();
  const [tempPassword, setTempPassword] = useState<{ name: string; password: string } | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const toggleActive = async (user: SaFacilityUser) => {
    setBusy(user.id);
    try {
      await saApi(`/users/${user.id}`, { method: "PATCH", body: { is_active: !user.is_active } });
      toast(user.is_active
        ? L(`عُطّل ${user.full_name}${user.role === "doctor" ? " — تحرر مقعده فوراً" : ""}`, `${user.full_name} deactivated${user.role === "doctor" ? " — seat freed immediately" : ""}`)
        : L(`فُعّل ${user.full_name}`, `${user.full_name} activated`));
      await reload();
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setBusy(null);
    }
  };

  const resetPassword = async (user: SaFacilityUser) => {
    setBusy(user.id);
    try {
      const body = await saApi<{ temporary_password: string }>(`/users/${user.id}/reset-password`, { method: "POST" });
      setTempPassword({ name: user.full_name, password: body.data.temporary_password });
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setBusy(null);
    }
  };

  const COLS = ".7fr 1.4fr 1fr 1.1fr .9fr .7fr 1.2fr";
  const admins = detail.users.filter((user) => user.role === "admin");
  const doctors = detail.users.filter((user) => user.role === "doctor");

  const renderRows = (users: SaFacilityUser[]) => users.map((user, i) => (
    <div key={user.id} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: COLS }}>
      <div>
        <span className="badge" style={user.role === "admin" ? { background: "rgba(42,111,151,.12)", color: "#2A6F97" } : { background: "#EAF6F7", color: "#0A5C64" }}>
          {user.role === "admin" ? L("أدمن", "Admin") : L("دكتور", "Doctor")}
        </span>
      </div>
      <div style={{ fontWeight: 700 }}>{user.full_name}</div>
      <div><bdi className="num">{user.username}</bdi></div>
      <div style={{ fontSize: 12.5 }}><bdi>{user.email ?? user.specialty ?? "—"}</bdi></div>
      <div style={{ fontSize: 12.5 }}>{user.clinic_name ?? "—"}</div>
      <div>
        <span className={user.is_active ? "badge success" : "badge neutral"}>
          {user.is_active ? L("نشط", "Active") : L("معطّل", "Disabled")}
        </span>
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <button className={user.is_active ? "btn-row warn" : "btn-row"} disabled={busy === user.id}
          onClick={() => void toggleActive(user)}>
          {user.is_active ? L("تعطيل", "Disable") : L("تفعيل", "Enable")}
        </button>
        <button className="btn-row" disabled={busy === user.id} onClick={() => void resetPassword(user)}>
          {L("إعادة تعيين كلمة المرور", "Reset password")}
        </button>
      </div>
    </div>
  ));

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <h3 style={{ fontSize: 15, fontWeight: 700, margin: 0, flex: 1 }}>
          {L("مستخدمو المنشأة", "Facility users")}{" "}
          <span style={{ color: "#5B7280", fontWeight: 400, fontSize: 13 }}>
            (<span className="num">{admins.length}</span> {L("أدمن ·", "admin ·")} <span className="num">{doctors.length}</span> {L("دكتور", "doctor")})
          </span>
        </h3>
        <button className="btn h40" onClick={() => setAdding(true)}>{L("+ إضافة مستخدم", "+ Add user")}</button>
      </div>
      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: COLS }}>
          <div>{L("الدور", "Role")}</div><div>{L("الاسم", "Name")}</div><div>{L("المستخدم", "Username")}</div>
          <div>{L("البريد / التخصص", "Email / specialty")}</div><div>{L("العيادة", "Clinic")}</div>
          <div>{L("الحالة", "Status")}</div><div>{L("إجراءات", "Actions")}</div>
        </div>
        {detail.users.length === 0 ? (
          <div className="grid-empty">{L("لا مستخدمين", "No users")}</div>
        ) : (
          <>
            {renderRows(admins)}
            {renderRows(doctors)}
          </>
        )}
      </div>
      <p style={{ fontSize: 12.5, color: "#5B7280", margin: "10px 0 0" }}>
        {L("تعطيل دكتور يحرر مقعده فوراً · تفعيله يتطلب مقعداً متاحاً (MDF-4221) · كل الإجراءات تُدوَّن في تدقيق المنشأة.",
           "Deactivating a doctor frees the seat immediately · activation requires an available seat (MDF-4221) · all actions are audit-logged.")}
      </p>

      {tempPassword !== null ? (
        <Modal title={L("كلمة مرور مؤقتة", "Temporary password")} onClose={() => setTempPassword(null)}>
          <p style={{ fontSize: 14, margin: "0 0 10px" }}>
            {L(`سلّم كلمة المرور التالية إلى ${tempPassword.name} — تُعرض مرة واحدة فقط:`,
               `Hand the following password to ${tempPassword.name} — shown only once:`)}
          </p>
          <div className="sub-box" style={{ textAlign: "center" }}>
            <bdi className="num" style={{ fontSize: 22, fontWeight: 800, letterSpacing: 1 }}>{tempPassword.password}</bdi>
          </div>
          <button className="btn" style={{ width: "100%", marginTop: 14 }} onClick={() => setTempPassword(null)}>
            {L("تم — إغلاق", "Done — close")}
          </button>
        </Modal>
      ) : null}

      {adding ? (
        <AddUserModal detail={detail} onClose={() => setAdding(false)} onDone={async () => { setAdding(false); await reload(); }} />
      ) : null}
    </>
  );
}

function AddUserModal({ detail, onClose, onDone }: {
  detail: SaFacilityDetail;
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const toast = useToast();
  const { L, lang } = useLang();
  const [role, setRole] = useState<"admin" | "doctor">("admin");
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [specialty, setSpecialty] = useState("");
  const [clinicId, setClinicId] = useState(detail.clinics[0]?.id ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { role, full_name: fullName, username, password };
      if (role === "admin") body["email"] = email;
      else {
        body["specialty"] = specialty;
        body["clinic_id"] = clinicId;
      }
      await saApi(`/facilities/${detail.facility.id}/users`, { method: "POST", body });
      toast(L(`أُنشئ الحساب ${username}`, `Account ${username} created`));
      await onDone();
    } catch (err) {
      setError(apiErrorText(err, lang, L));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={L("إضافة مستخدم للمنشأة", "Add facility user")} onClose={onClose}>
      <div className="tabs" role="tablist" style={{ marginBottom: 12 }}>
        <button role="tab" aria-selected={role === "admin"} className={role === "admin" ? "tab active" : "tab"} onClick={() => setRole("admin")}>
          {L("أدمن منشأة", "Facility admin")}
        </button>
        <button role="tab" aria-selected={role === "doctor"} className={role === "doctor" ? "tab active" : "tab"} onClick={() => setRole("doctor")}>
          {L("دكتور", "Doctor")}
        </button>
      </div>
      <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <Field label={L("الاسم الكامل", "Full name")} value={fullName} onChange={(event) => setFullName(event.target.value)} required minLength={2} />
        <Field label={L("اسم المستخدم", "Username")} ltr value={username} onChange={(event) => setUsername(event.target.value)} required minLength={3} />
        <Field label={L("كلمة المرور", "Password")} ltr type="password" value={password} onChange={(event) => setPassword(event.target.value)} required minLength={8} />
        {role === "admin" ? (
          <Field label={L("البريد (قناة الاستعادة — إلزامي)", "Email (recovery channel — required)")} ltr type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        ) : (
          <>
            <Field label={L("التخصص", "Specialty")} value={specialty} onChange={(event) => setSpecialty(event.target.value)} required minLength={2} />
            <label className="field-label">{L("العيادة", "Clinic")}</label>
            <select className="field" value={clinicId} onChange={(event) => setClinicId(event.target.value)} required>
              {detail.clinics.length === 0 ? <option value="">{L("لا عيادات — أنشئها من حساب أدمن المنشأة", "No clinics — create from the facility admin account")}</option> : null}
              {detail.clinics.map((clinic) => <option key={clinic.id} value={clinic.id}>{clinic.name}</option>)}
            </select>
            <p style={{ fontSize: 12.5, color: "#5B7280", margin: "6px 0 0" }}>
              {L("إنشاء دكتور يستهلك مقعداً — يفشل إن لا مقاعد متاحة (MDF-4221).", "Creating a doctor consumes a seat — fails if none available (MDF-4221).")}
            </p>
          </>
        )}
        {error !== null ? <p style={{ color: "#C0392B", fontSize: 12.5, fontWeight: 700, margin: "10px 0 0" }}>{error}</p> : null}
        <button type="submit" className="btn" style={{ width: "100%", marginTop: 14 }} disabled={busy || (role === "doctor" && clinicId === "")}>
          {busy ? <span className="spinner" /> : null} {L("إنشاء الحساب", "Create account")}
        </button>
      </form>
    </Modal>
  );
}

/* ===== الفواتير ===== */
function InvoicesTab({ detail, reload }: { detail: SaFacilityDetail; reload: () => Promise<void> }) {
  const toast = useToast();
  const { L, lang } = useLang();
  const [busy, setBusy] = useState<string | null>(null);
  const [issuing, setIssuing] = useState(false);

  const setStatus = async (invoice: SaInvoice, status: "paid" | "void") => {
    setBusy(invoice.id);
    try {
      await saApi(`/invoices/${invoice.id}`, { method: "PATCH", body: { status } });
      toast(status === "paid"
        ? L(`سُجّل سداد ${invoice.number} — يُرفع التعليق إن لم تبقَ متأخرات`, `${invoice.number} marked paid — suspension lifts if no overdue remains`)
        : L(`أُلغيت ${invoice.number}`, `${invoice.number} voided`));
      await reload();
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setBusy(null);
    }
  };

  const issueInvoice = async () => {
    setIssuing(true);
    try {
      const body = await saApi<SaInvoice>(`/facilities/${detail.facility.id}/invoices`, { method: "POST", body: {} });
      toast(L(`أُصدرت الفاتورة ${body.data.number} (${fmtSar(body.data.total_sar)} SAR شامل الضريبة)`,
              `Invoice ${body.data.number} issued (${fmtSar(body.data.total_sar)} SAR incl. VAT)`));
      await reload();
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setIssuing(false);
    }
  };

  const COLS = "1.1fr 1.4fr .8fr .8fr .9fr .8fr 1.1fr";
  const used = detail.subscription?.seats_used ?? 0;
  const price = detail.subscription?.plan_info?.seat_price_sar;

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
        <h3 style={{ fontSize: 15, fontWeight: 700, margin: 0, flex: 1 }}>{L("فواتير المنشأة", "Facility invoices")}</h3>
        <button className="btn h40" disabled={issuing || used === 0} onClick={() => void issueInvoice()}>
          {issuing ? <span className="spinner" /> : null}{" "}
          {L(`إصدار فاتورة الدورة (${used} دكتور نشط${price ? ` × ${fmtSar(price)} SAR` : ""})`,
             `Issue cycle invoice (${used} active doctors${price ? ` × ${fmtSar(price)} SAR` : ""})`)}
        </button>
      </div>
      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: COLS }}>
          <div>{L("الفاتورة", "Invoice")}</div><div>{L("الفترة", "Period")}</div><div>{L("المبلغ", "Amount")}</div>
          <div>{L("ضريبة 15%", "VAT 15%")}</div><div>{L("الإجمالي", "Total")}</div><div>{L("الحالة", "Status")}</div><div>{L("إجراءات", "Actions")}</div>
        </div>
        {detail.invoices.length === 0 ? (
          <div className="grid-empty">{L("لا فواتير بعد", "No invoices yet")}</div>
        ) : (
          detail.invoices.map((invoice, i) => {
            const meta = INVOICE_STATUS[invoice.status];
            const open = invoice.status === "due" || invoice.status === "overdue";
            return (
              <div key={invoice.id} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: COLS }}>
                <div><bdi>{invoice.number}</bdi></div>
                <div><bdi style={{ fontSize: 12.5 }}>{invoice.period_start.slice(0, 10)} → {invoice.period_end.slice(0, 10)}</bdi></div>
                <div><bdi>{fmtSar(invoice.amount_sar)}</bdi></div>
                <div><bdi>{fmtSar(invoice.vat_sar)}</bdi></div>
                <div style={{ fontWeight: 700 }}><bdi>{fmtSar(invoice.total_sar)}</bdi></div>
                <div><span className={meta.cls}>{L(meta.ar, meta.en)}</span></div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {open ? (
                    <>
                      <button className="btn-row" disabled={busy === invoice.id} onClick={() => void setStatus(invoice, "paid")}>
                        {L("تسجيل سداد", "Mark paid")}
                      </button>
                      <button className="btn-row danger" disabled={busy === invoice.id} onClick={() => {
                        if (window.confirm(L(`إلغاء الفاتورة ${invoice.number}؟`, `Void invoice ${invoice.number}?`))) {
                          void setStatus(invoice, "void");
                        }
                      }}>
                        {L("إلغاء", "Void")}
                      </button>
                    </>
                  ) : (
                    <span style={{ color: "#5B7280", fontSize: 12.5 }}>
                      {invoice.paid_at !== null ? fmtDateTime(invoice.paid_at) : "—"}
                    </span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
      <p style={{ fontSize: 12.5, color: "#5B7280", margin: "10px 0 0" }}>
        {L("المبلغ = عدد الدكاترة النشطين × سعر مقعد الباقة + ضريبة 15% مفصولة · تسجيل السداد اليدوي يرفع تعليق المنشأة إن لم تبقَ متأخرات.",
           "Amount = active doctors × plan seat price + itemized 15% VAT · manual settlement lifts suspension when no overdue invoices remain.")}
      </p>
    </>
  );
}

/* ===== الصفحة ===== */
function FacilityDetailInner({ facilityId }: { facilityId: string }) {
  const toast = useToast();
  const { L, lang } = useLang();
  const [tab, setTab] = useState<"status" | "users" | "invoices">("status");
  const [detail, setDetail] = useState<SaFacilityDetail | null>(null);
  const [plans, setPlans] = useState<SaPlan[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [detailBody, plansBody] = await Promise.all([
        saApi<SaFacilityDetail>(`/facilities/${facilityId}`),
        saApi<SaPlan[]>("/plans"),
      ]);
      setDetail(detailBody.data);
      setPlans(plansBody.data);
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setLoading(false);
    }
  }, [facilityId, toast, lang, L]);

  useEffect(() => { void load(); }, [load]);

  if (loading) return <div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div>;
  if (detail === null) return <div className="grid-empty">{L("تعذر تحميل المنشأة", "Could not load the facility")}</div>;

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "0 0 12px", flexWrap: "wrap" }}>
        <h1 style={{ fontSize: 20, fontWeight: 800, color: "#0A5C64", margin: 0, flex: 1 }}>{detail.facility.name}</h1>
        <span className={FACILITY_STATUS_META[detail.facility.status].cls}>
          {L(FACILITY_STATUS_META[detail.facility.status].ar, FACILITY_STATUS_META[detail.facility.status].en)}
        </span>
      </div>
      <Tabs
        tabs={[
          { key: "status", label: L("الحالة والاشتراك", "Status & subscription") },
          { key: "users", label: L("المستخدمون", "Users") },
          { key: "invoices", label: L("الفواتير", "Invoices") },
        ]}
        active={tab}
        onChange={setTab}
      />
      {tab === "status" ? <StatusSubscriptionTab detail={detail} plans={plans} reload={load} /> : null}
      {tab === "users" ? <UsersTab detail={detail} reload={load} /> : null}
      {tab === "invoices" ? <InvoicesTab detail={detail} reload={load} /> : null}
    </>
  );
}

export default function SaFacilityDetailPage() {
  const params = useParams<{ id: string }>();
  const { L } = useLang();
  return (
    <SaShell title={L("إدارة منشأة", "Manage facility")}>
      <main className="page-wrap">
        <FacilityDetailInner facilityId={params.id} />
      </main>
    </SaShell>
  );
}
