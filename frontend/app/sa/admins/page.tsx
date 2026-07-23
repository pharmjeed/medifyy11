"use client";

/** W-SA-11 — إدارة حسابات السوبر أدمن (owner حصراً): دعوة بدرجة، تغيير درجة، تعطيل، إعادة كلمة مرور.
 *  الإجراءات حسّاسة: عند تفعيل 2FA يُطلب رمز حي (X-SA-Reauth) — MDF-4015 reason=reauth_required. */

import { useCallback, useEffect, useState } from "react";
import { SaShell } from "@/components/SaShell";
import { Field, Modal, fmtDateTime, useToast } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import type { Lang } from "@/lib/i18n";
import { saApi } from "@/lib/sa";
import type { SaAdmin, SaApiOptions, SaRole } from "@/lib/sa";

type LFn = (ar: string, en: string) => string;

const ROLE_META: Record<SaRole, { ar: string; en: string; desc_ar: string; desc_en: string }> = {
  owner: { ar: "مالك", en: "Owner", desc_ar: "كل شيء — بما فيه الحسابات والتسعير والأمان", desc_en: "Everything — accounts, pricing, security" },
  ops: { ar: "تشغيل", en: "Ops", desc_ar: "المنشآت والمستخدمون والفواتير — لا تسعير ولا حسابات", desc_en: "Facilities, users, invoices — no pricing/accounts" },
  finance: { ar: "مالية", en: "Finance", desc_ar: "الفواتير والتقارير فقط", desc_en: "Invoices & reports only" },
  support: { ar: "دعم", en: "Support", desc_ar: "قراءة فقط (تجميعات)", desc_en: "Read-only (aggregates)" },
  read_only: { ar: "قراءة", en: "Read-only", desc_ar: "عرض اللوحات فقط", desc_en: "View dashboards only" },
};

function apiErrorText(err: unknown, lang: Lang, L: LFn): string {
  return err instanceof ApiError ? `${err.text(lang)} (${err.code})` : L("تعذر الاتصال بالخادم", "Could not reach the server");
}

/** ينفّذ نداءً حسّاساً؛ إن طلب الخادم إعادة مصادقة يسأل عن رمز حي ويعيد المحاولة مرة واحدة. */
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

function InviteModal({ onClose, onDone }: { onClose: () => void; onDone: () => Promise<void> }) {
  const toast = useToast();
  const { L, lang } = useLang();
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<SaRole>("ops");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await saSensitive(L, "/admins", {
        method: "POST",
        body: { username, full_name: fullName, email: email || null, password, role },
      });
      toast(L(`أُنشئ حساب ${username} بدرجة ${L(ROLE_META[role].ar, ROLE_META[role].en)}`, `Account ${username} created as ${ROLE_META[role].en}`));
      await onDone();
    } catch (err) {
      setError(apiErrorText(err, lang, L));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={L("حساب منصة جديد", "New platform account")} onClose={onClose}>
      <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <Field label={L("اسم المستخدم (لاتيني)", "Username (latin)")} ltr value={username} minLength={3}
          onChange={(event) => setUsername(event.target.value)} required pattern="[a-z0-9][a-z0-9\.\-_]*" />
        <Field label={L("الاسم الكامل", "Full name")} value={fullName} minLength={2}
          onChange={(event) => setFullName(event.target.value)} required />
        <Field label={L("البريد (اختياري)", "Email (optional)")} ltr type="email" value={email}
          onChange={(event) => setEmail(event.target.value)} />
        <Field label={L("كلمة المرور (10 أحرف فأكثر)", "Password (10+ chars)")} ltr type="password" value={password}
          minLength={10} onChange={(event) => setPassword(event.target.value)} required />
        <label className="field-label">{L("الدرجة", "Grade")}</label>
        <select className="field" value={role} onChange={(event) => setRole(event.target.value as SaRole)}>
          {(Object.keys(ROLE_META) as SaRole[]).map((key) => (
            <option key={key} value={key}>{L(ROLE_META[key].ar, ROLE_META[key].en)} — {L(ROLE_META[key].desc_ar, ROLE_META[key].desc_en)}</option>
          ))}
        </select>
        {error !== null ? <p style={{ color: "#d94b4b", fontSize: 12.5, fontWeight: 700, margin: "10px 0 0" }}>{error}</p> : null}
        <button type="submit" className="btn" style={{ width: "100%", marginTop: 14 }} disabled={busy}>
          {busy ? <span className="spinner" /> : null} {L("إنشاء الحساب", "Create account")}
        </button>
      </form>
    </Modal>
  );
}

function AdminsInner() {
  const toast = useToast();
  const { L, lang } = useLang();
  const [rows, setRows] = useState<SaAdmin[]>([]);
  const [loading, setLoading] = useState(true);
  const [inviting, setInviting] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [tempPassword, setTempPassword] = useState<{ name: string; password: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const body = await saApi<SaAdmin[]>("/admins");
      setRows(body.data);
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setLoading(false);
    }
  }, [toast, lang, L]);

  useEffect(() => { void load(); }, [load]);

  const patch = async (admin: SaAdmin, body: Record<string, unknown>, doneMsg: string) => {
    setBusy(admin.id);
    try {
      await saSensitive(L, `/admins/${admin.id}`, { method: "PATCH", body });
      toast(doneMsg);
      await load();
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setBusy(null);
    }
  };

  const resetPassword = async (admin: SaAdmin) => {
    setBusy(admin.id);
    try {
      const body = await saSensitive<{ temporary_password: string }>(L, `/admins/${admin.id}/reset-password`, { method: "POST" });
      setTempPassword({ name: admin.full_name, password: body.data.temporary_password });
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setBusy(null);
    }
  };

  const COLS = "1.2fr 1fr 1fr .8fr .7fr .9fr 1.6fr";

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, margin: 0, flex: 1 }}>
          {L("حسابات السوبر أدمن", "Super admin accounts")}{" "}
          <span style={{ color: "#5c7096", fontWeight: 400, fontSize: 13 }}>(<span className="num">{rows.length}</span>)</span>
        </h2>
        <button className="btn h40" onClick={() => setInviting(true)}>{L("+ حساب جديد", "+ New account")}</button>
      </div>

      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: COLS }}>
          <div>{L("الاسم", "Name")}</div><div>{L("المستخدم", "Username")}</div><div>{L("الدرجة", "Grade")}</div>
          <div>{L("2FA", "2FA")}</div><div>{L("الحالة", "Status")}</div><div>{L("آخر دخول", "Last login")}</div><div>{L("إجراءات", "Actions")}</div>
        </div>
        {loading ? (
          <div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div>
        ) : (
          rows.map((admin, i) => (
            <div key={admin.id} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: COLS }}>
              <div style={{ fontWeight: 700 }}>{admin.full_name}</div>
              <div><bdi className="num">{admin.username}</bdi></div>
              <div>
                <select className="field" style={{ margin: 0, height: 32, padding: "2px 8px", fontSize: 12.5 }}
                  value={admin.role} disabled={busy === admin.id}
                  onChange={(event) => void patch(admin, { role: event.target.value },
                    L(`غُيّرت درجة ${admin.username}`, `${admin.username} grade changed`))}>
                  {(Object.keys(ROLE_META) as SaRole[]).map((key) => (
                    <option key={key} value={key}>{L(ROLE_META[key].ar, ROLE_META[key].en)}</option>
                  ))}
                </select>
              </div>
              <div>
                <span className={admin.totp_enabled ? "badge success" : "badge warn"}>
                  {admin.totp_enabled ? L("مفعّل", "On") : L("غير مفعّل", "Off")}
                </span>
              </div>
              <div>
                <span className={admin.is_active ? "badge success" : "badge neutral"}>
                  {admin.is_active ? L("نشط", "Active") : L("معطّل", "Disabled")}
                </span>
              </div>
              <div style={{ fontSize: 12.5 }}>{admin.last_login_at ? fmtDateTime(admin.last_login_at) : "—"}</div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <button className={admin.is_active ? "btn-row warn" : "btn-row"} disabled={busy === admin.id}
                  onClick={() => void patch(admin, { is_active: !admin.is_active },
                    admin.is_active ? L(`عُطّل ${admin.username}`, `${admin.username} disabled`) : L(`فُعّل ${admin.username}`, `${admin.username} enabled`))}>
                  {admin.is_active ? L("تعطيل", "Disable") : L("تفعيل", "Enable")}
                </button>
                <button className="btn-row" disabled={busy === admin.id} onClick={() => void resetPassword(admin)}>
                  {L("إعادة تعيين كلمة المرور", "Reset password")}
                </button>
              </div>
            </div>
          ))
        )}
      </div>
      <p style={{ fontSize: 12.5, color: "#5c7096", margin: "10px 0 0" }}>
        {L("آخر حساب مالك فعّال محمي من التعطيل والتخفيض (MDF-4229) · كل تغيير يُدوَّن في سجل المنصة الموحّد.",
           "The last active owner account cannot be disabled or downgraded (MDF-4229) · every change is recorded in the unified platform audit.")}
      </p>

      {tempPassword !== null ? (
        <Modal title={L("كلمة مرور مؤقتة", "Temporary password")} onClose={() => setTempPassword(null)}>
          <p style={{ fontSize: 14, margin: "0 0 10px" }}>
            {L(`سلّمها إلى ${tempPassword.name} — تُعرض مرة واحدة فقط:`, `Hand it to ${tempPassword.name} — shown only once:`)}
          </p>
          <div className="sub-box" style={{ textAlign: "center" }}>
            <bdi className="num" style={{ fontSize: 20, fontWeight: 800, letterSpacing: 1 }}>{tempPassword.password}</bdi>
          </div>
          <button className="btn" style={{ width: "100%", marginTop: 14 }} onClick={() => setTempPassword(null)}>
            {L("تم — إغلاق", "Done — close")}
          </button>
        </Modal>
      ) : null}

      {inviting ? (
        <InviteModal onClose={() => setInviting(false)} onDone={async () => { setInviting(false); await load(); }} />
      ) : null}
    </>
  );
}

export default function SaAdminsPage() {
  const { L } = useLang();
  return (
    <SaShell title={L("حسابات المنصة", "Platform accounts")}>
      <main className="page-wrap">
        <AdminsInner />
      </main>
    </SaShell>
  );
}
