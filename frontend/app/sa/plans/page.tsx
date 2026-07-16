"use client";

/** تسعير الدكتور (W-SA-05) — تكلفة كل دكتور لكل دورة فوترة، يحددها مالك المنصة (DOC-20 §٠.١ تعديل ٢).
 *  تغيير السعر إجراء حسّاس: يطلب رمز مصادقة حياً عند تفعيل 2FA، ويسري على الفواتير اللاحقة فقط. */

import { useCallback, useEffect, useState } from "react";
import { SaShell } from "@/components/SaShell";
import { Field, Modal, useToast } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import type { Lang } from "@/lib/i18n";
import { saApi } from "@/lib/sa";
import type { SaApiOptions } from "@/lib/sa";
import type { SaPlan } from "@/lib/types";

type LFn = (ar: string, en: string) => string;

/** نداء حسّاس: عند طلب الخادم إعادة مصادقة يسأل عن رمز حي ويعيد المحاولة مرة واحدة. */
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

const COLS = ".9fr 1.2fr 1fr .9fr .9fr .7fr .9fr";

function fmtSar(value: string): string {
  const num = Number(value);
  if (Number.isNaN(num)) return value;
  return num.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function apiErrorText(err: unknown, lang: Lang, L: LFn): string {
  return err instanceof ApiError ? `${err.text(lang)} (${err.code})` : L("تعذر الاتصال بالخادم", "Could not reach the server");
}

function PlanModal({ plan, onClose, onDone }: {
  plan: SaPlan | null; // null = إنشاء
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const toast = useToast();
  const { L, lang } = useLang();
  const [code, setCode] = useState(plan?.code ?? "");
  const [nameAr, setNameAr] = useState(plan?.name_ar ?? "");
  const [nameEn, setNameEn] = useState(plan?.name_en ?? "");
  const [price, setPrice] = useState(plan?.seat_price_sar ?? "");
  const [cycle, setCycle] = useState<"monthly" | "yearly">(plan?.billing_cycle ?? "monthly");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      if (plan === null) {
        await saSensitive(L, "/plans", {
          method: "POST",
          body: { code, name_ar: nameAr, name_en: nameEn, seat_price_sar: price, billing_cycle: cycle },
        });
        toast(L(`أُنشئت دورة التسعير ${code}`, `Pricing cycle ${code} created`));
      } else {
        await saSensitive(L, `/plans/${plan.id}`, {
          method: "PATCH",
          body: { name_ar: nameAr, name_en: nameEn, seat_price_sar: price },
        });
        toast(L(`حُدّثت تكلفة الدكتور في ${plan.code} — تسري على الفواتير اللاحقة فقط`,
                `Doctor cost updated for ${plan.code} — applies to future invoices only`));
      }
      await onDone();
    } catch (err) {
      setError(apiErrorText(err, lang, L));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={plan === null ? L("دورة تسعير جديدة", "New pricing cycle") : L(`تعديل ${plan.code}`, `Edit ${plan.code}`)} onClose={onClose}>
      <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        {plan === null ? (
          <>
            <Field label={L("الرمز (لاتيني — ثابت بعد الإنشاء)", "Code (latin — immutable after creation)")} ltr
              placeholder="premium-monthly" value={code} pattern="[a-z0-9][a-z0-9\-_]*"
              onChange={(event) => setCode(event.target.value)} required minLength={2} maxLength={40} />
            <label className="field-label">{L("دورة الفوترة", "Billing cycle")}</label>
            <select className="field" value={cycle} onChange={(event) => setCycle(event.target.value as "monthly" | "yearly")}>
              <option value="monthly">{L("شهرية", "Monthly")}</option>
              <option value="yearly">{L("سنوية", "Yearly")}</option>
            </select>
          </>
        ) : null}
        <Field label={L("الاسم بالعربية", "Arabic name")} value={nameAr} onChange={(event) => setNameAr(event.target.value)} required minLength={2} />
        <Field label={L("الاسم بالإنجليزية", "English name")} ltr value={nameEn} onChange={(event) => setNameEn(event.target.value)} required minLength={2} />
        <Field label={L("تكلفة الدكتور (SAR — قبل الضريبة)", "Cost per doctor (SAR — before VAT)")} ltr type="number" min={0} step="0.01"
          value={price} onChange={(event) => setPrice(event.target.value)} required />
        {error !== null ? <p style={{ color: "#C0392B", fontSize: 12.5, fontWeight: 700, margin: "10px 0 0" }}>{error}</p> : null}
        <button type="submit" className="btn" style={{ width: "100%", marginTop: 14 }} disabled={busy}>
          {busy ? <span className="spinner" /> : null} {plan === null ? L("إنشاء الباقة", "Create plan") : L("حفظ التعديلات", "Save changes")}
        </button>
      </form>
    </Modal>
  );
}

function PlansInner() {
  const toast = useToast();
  const { L, lang } = useLang();
  const [rows, setRows] = useState<SaPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<SaPlan | null | "new">(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const body = await saApi<SaPlan[]>("/plans");
      setRows(body.data);
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setLoading(false);
    }
  }, [toast, lang, L]);

  useEffect(() => { void load(); }, [load]);

  const toggleActive = async (plan: SaPlan) => {
    setBusy(plan.id);
    try {
      await saApi(`/plans/${plan.id}`, { method: "PATCH", body: { is_active: !plan.is_active } });
      toast(plan.is_active
        ? L(`أُوقفت ${plan.code} — المنشآت الحالية تبقى عليها ولا إسناد جديد`, `${plan.code} deactivated — current facilities keep it, no new assignment`)
        : L(`فُعّلت ${plan.code}`, `${plan.code} activated`));
      await load();
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, margin: 0, flex: 1 }}>{L("تكلفة الدكتور لكل دورة فوترة", "Cost per doctor by billing cycle")}</h2>
        <button className="btn h40" onClick={() => setEditing("new")}>{L("+ دورة تسعير جديدة", "+ New pricing cycle")}</button>
      </div>
      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: COLS }}>
          <div>{L("الرمز", "Code")}</div><div>{L("الاسم", "Name")}</div>
          <div>{L("تكلفة الدكتور", "Cost / doctor")}</div><div>{L("الدورة", "Cycle")}</div>
          <div>{L("منشآت عليها", "Facilities on it")}</div><div>{L("الحالة", "Status")}</div><div>{L("إجراءات", "Actions")}</div>
        </div>
        {loading ? (
          <div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div>
        ) : rows.length === 0 ? (
          <div className="grid-empty">{L("لا باقات — أنشئ الأولى", "No plans — create the first")}</div>
        ) : (
          rows.map((plan, i) => (
            <div key={plan.id} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: COLS }}>
              <div><bdi className="num" style={{ fontWeight: 700 }}>{plan.code}</bdi></div>
              <div>{lang === "ar" ? plan.name_ar : plan.name_en}</div>
              <div><bdi>{fmtSar(plan.seat_price_sar)} SAR</bdi></div>
              <div>{plan.billing_cycle === "monthly" ? L("شهرية", "Monthly") : L("سنوية", "Yearly")}</div>
              <div className="num">{plan.facilities_count}</div>
              <div>
                <span className={plan.is_active ? "badge success" : "badge neutral"}>
                  {plan.is_active ? L("فعّالة", "Active") : L("موقوفة", "Inactive")}
                </span>
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <button className="btn-row" disabled={busy === plan.id} onClick={() => setEditing(plan)}>{L("تعديل", "Edit")}</button>
                <button className={plan.is_active ? "btn-row warn" : "btn-row"} disabled={busy === plan.id} onClick={() => void toggleActive(plan)}>
                  {plan.is_active ? L("إيقاف", "Deactivate") : L("تفعيل", "Activate")}
                </button>
              </div>
            </div>
          ))
        )}
      </div>
      <p style={{ fontSize: 12.5, color: "#5B7280", margin: "10px 0 0" }}>
        {L("الفاتورة = عدد الدكاترة النشطين × تكلفة الدكتور + ضريبة 15% مفصولة · تعديل التكلفة لا يمس الفواتير الصادرة ويظهر فوراً في صفحة تسجيل المنشآت.",
           "Invoice = active doctors × cost per doctor + itemized 15% VAT · cost changes never touch issued invoices and appear immediately on the facility signup page.")}
      </p>
      {editing !== null ? (
        <PlanModal plan={editing === "new" ? null : editing} onClose={() => setEditing(null)}
          onDone={async () => { setEditing(null); await load(); }} />
      ) : null}
    </>
  );
}

export default function SaPlansPage() {
  const { L } = useLang();
  return (
    <SaShell title={L("تسعير الدكتور", "Doctor pricing")}>
      <main className="page-wrap narrow">
        <PlansInner />
      </main>
    </SaShell>
  );
}
