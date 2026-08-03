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
import type { FeatureCatalogItem, FeatureMap, SaFeatureCatalog, SaPlan } from "@/lib/types";

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

const COLS = ".85fr 1.1fr .9fr .7fr .8fr .8fr .65fr 1.15fr";

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
  const [monthly, setMonthly] = useState(plan?.seat_price_sar ?? "");
  const [yearly, setYearly] = useState(plan?.seat_price_yearly_sar ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      if (monthly.trim() === "" && yearly.trim() === "") {
        setError(L("باقة بلا سعر: حدّد السعر الشهري أو السنوي على الأقل",
                   "A plan needs a price: set the monthly or the yearly cost at least"));
        return;
      }
      const prices = {
        seat_price_sar: monthly.trim() === "" ? null : monthly,
        seat_price_yearly_sar: yearly.trim() === "" ? null : yearly,
      };
      if (plan === null) {
        await saSensitive(L, "/plans", {
          method: "POST",
          body: { code, name_ar: nameAr, name_en: nameEn, ...prices },
        });
        toast(L(`أُنشئت الباقة ${code}`, `Plan ${code} created`));
      } else {
        // سعر مُفرَّغ = سحب الباقة من تلك الدورة — يُصرَّح به لأن PATCH لا يميّز null عن «لم يُذكر»
        const clear: string[] = [];
        if (prices.seat_price_sar === null) clear.push("monthly");
        if (prices.seat_price_yearly_sar === null) clear.push("yearly");
        await saSensitive(L, `/plans/${plan.id}`, {
          method: "PATCH",
          body: { name_ar: nameAr, name_en: nameEn, ...prices, clear_prices: clear },
        });
        toast(L(`حُدّثت الباقة ${plan.code} — الأسعار تسري على الفواتير اللاحقة فقط`,
                `Plan ${plan.code} updated — prices apply to future invoices only`));
      }
      await onDone();
    } catch (err) {
      setError(apiErrorText(err, lang, L));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={plan === null ? L("باقة جديدة", "New plan") : L(`تعديل ${plan.code}`, `Edit ${plan.code}`)} onClose={onClose}>
      <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        {plan === null ? (
          <Field label={L("الرمز (لاتيني — ثابت بعد الإنشاء)", "Code (latin — immutable after creation)")} ltr
            placeholder="premium" value={code} pattern="[a-z0-9][a-z0-9\-_]*"
            onChange={(event) => setCode(event.target.value)} required minLength={2} maxLength={40} />
        ) : null}
        <Field label={L("الاسم بالعربية", "Arabic name")} value={nameAr} onChange={(event) => setNameAr(event.target.value)} required minLength={2} />
        <Field label={L("الاسم بالإنجليزية", "English name")} ltr value={nameEn} onChange={(event) => setNameEn(event.target.value)} required minLength={2} />
        <Field label={L("تكلفة الدكتور شهرياً (SAR — قبل الضريبة)", "Cost per doctor, monthly (SAR — before VAT)")} ltr type="number" min={0} step="0.01"
          value={monthly} onChange={(event) => setMonthly(event.target.value)} />
        <Field label={L("تكلفة الدكتور سنوياً (SAR — قبل الضريبة)", "Cost per doctor, yearly (SAR — before VAT)")} ltr type="number" min={0} step="0.01"
          value={yearly} onChange={(event) => setYearly(event.target.value)} />
        <p style={{ fontSize: 12, color: "#5c7096", margin: "6px 0 0" }}>
          {L("اترك خانة فارغة إن كانت الباقة لا تُباع بتلك الدورة — لا بد من سعر واحد على الأقل.",
             "Leave a field empty if the plan is not sold on that cycle — at least one price is required.")}
        </p>
        {error !== null ? <p style={{ color: "#d94b4b", fontSize: 12.5, fontWeight: 700, margin: "10px 0 0" }}>{error}</p> : null}
        <button type="submit" className="btn" style={{ width: "100%", marginTop: 14 }} disabled={busy}>
          {busy ? <span className="spinner" /> : null} {plan === null ? L("إنشاء الباقة", "Create plan") : L("حفظ التعديلات", "Save changes")}
        </button>
      </form>
    </Modal>
  );
}

/** ما تُظهره الباقة للدكتور (W-SA-05 — قرار مالك 2026-08-03).
 *  الترتيب والتجميع من كتالوج الخادم (`app/features.py`)؛ الأساسية معروضة مقفولة لتكتمل الصورة. */
function FeaturesModal({ plan, catalog, onClose, onDone }: {
  plan: SaPlan;
  catalog: SaFeatureCatalog;
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const toast = useToast();
  const { L, lang } = useLang();
  const [draft, setDraft] = useState<FeatureMap>({ ...plan.features });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const optional = catalog.features.filter((item) => !item.core);
  const onCount = optional.filter((item) => draft[item.key] !== false).length;
  const dirty = optional.some((item) => (draft[item.key] !== false) !== (plan.features[item.key] !== false));

  const setAll = (value: boolean) => {
    const next: FeatureMap = { ...draft };
    for (const item of optional) next[item.key] = value;
    setDraft(next);
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const body: FeatureMap = {};
      for (const item of optional) body[item.key] = draft[item.key] !== false;
      await saSensitive(L, `/plans/${plan.id}/features`, { method: "PUT", body: { features: body } });
      toast(L(`حُدّثت مميزات ${plan.code} — تسري فوراً على ${plan.facilities_count} منشأة`,
              `${plan.code} features updated — effective immediately for ${plan.facilities_count} facility/ies`));
      await onDone();
    } catch (err) {
      setError(apiErrorText(err, lang, L));
    } finally {
      setBusy(false);
    }
  };

  const row = (item: FeatureCatalogItem) => {
    const enabled = item.core || draft[item.key] !== false;
    return (
      <label key={item.key} style={{
        display: "flex", gap: 10, alignItems: "flex-start", padding: "9px 10px", borderRadius: 8,
        cursor: item.core ? "default" : "pointer", background: enabled ? "rgba(0,115,109,.05)" : "transparent",
        border: "1px solid", borderColor: enabled ? "#d6f5f2" : "transparent",
      }}>
        <input type="checkbox" checked={enabled} disabled={item.core} style={{ marginTop: 3 }}
          onChange={(event) => setDraft({ ...draft, [item.key]: event.target.checked })} />
        <span style={{ flex: 1, minWidth: 0 }}>
          <span style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <strong style={{ fontSize: 13.5 }}>{lang === "ar" ? item.name_ar : item.name_en}</strong>
            {item.core ? <span className="badge neutral">{L("أساسية — لا تُطفأ", "Core — always on")}</span> : null}
            <bdi className="tech-badge" style={{ fontSize: 11 }}>{item.key}</bdi>
          </span>
          <span style={{ display: "block", fontSize: 12, color: "#5c7096", marginTop: 2 }}>
            {lang === "ar" ? item.desc_ar : item.desc_en}
          </span>
        </span>
      </label>
    );
  };

  return (
    <Modal title={L(`مميزات ${plan.code} — ما يراه الدكتور`, `${plan.code} features — what the doctor sees`)} onClose={onClose} wide>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
        <span className="badge success"><span className="num">{onCount}</span> / <span className="num">{optional.length}</span> {L("مفعّلة", "enabled")}</span>
        <span style={{ flex: 1 }} />
        <button type="button" className="btn-row" onClick={() => setAll(true)}>{L("تفعيل الكل", "Enable all")}</button>
        <button type="button" className="btn-row" onClick={() => setAll(false)}>{L("إطفاء الكل", "Disable all")}</button>
      </div>
      <div style={{ maxHeight: "58vh", overflowY: "auto", paddingInlineEnd: 4 }}>
        {catalog.groups.map((group) => {
          const items = catalog.features.filter((item) => item.group === group.code);
          if (items.length === 0) return null;
          return (
            <div key={group.code} style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 12.5, fontWeight: 800, color: "#005a55", margin: "6px 0 4px" }}>
                {lang === "ar" ? group.name_ar : group.name_en}
              </div>
              {items.map(row)}
            </div>
          );
        })}
      </div>
      {error !== null ? <p style={{ color: "#d94b4b", fontSize: 12.5, fontWeight: 700, margin: "10px 0 0" }}>{error}</p> : null}
      <p style={{ fontSize: 12, color: "#5c7096", margin: "10px 0 0" }}>
        {L("التغيير يسري فوراً على كل منشأة على هذه الباقة (بلا إعادة دخول)، ولا يمس التسعير ولا الفواتير الصادرة. المنع يُفرض في الخادم لا في الواجهة.",
           "Changes take effect immediately for every facility on this plan (no re-login), and never touch pricing or issued invoices. Enforcement is server-side, not in the UI.")}
      </p>
      <button type="button" className="btn" style={{ width: "100%", marginTop: 12 }} disabled={busy || !dirty} onClick={() => void submit()}>
        {busy ? <span className="spinner" /> : null} {L("حفظ المميزات", "Save features")}
      </button>
    </Modal>
  );
}

function PlansInner() {
  const toast = useToast();
  const { L, lang } = useLang();
  const [rows, setRows] = useState<SaPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<SaPlan | null | "new">(null);
  const [featuresOf, setFeaturesOf] = useState<SaPlan | null>(null);
  const [catalog, setCatalog] = useState<SaFeatureCatalog | null>(null);
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

  // كتالوج المميزات مصدره الكود — يُجلب مرة ويُشارَك بين كل الباقات
  useEffect(() => {
    void (async () => {
      try {
        const body = await saApi<SaFeatureCatalog>("/features");
        setCatalog(body.data);
      } catch { /* بلا كتالوج تبقى الصفحة تسعيراً فقط */ }
    })();
  }, []);

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
        <h2 style={{ fontSize: 16, fontWeight: 700, margin: 0, flex: 1 }}>{L("الباقات — تكلفة الدكتور وما تُظهره له", "Plans — cost per doctor and what it shows them")}</h2>
        <button className="btn h40" onClick={() => setEditing("new")}>{L("+ باقة جديدة", "+ New plan")}</button>
      </div>
      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: COLS }}>
          <div>{L("الرمز", "Code")}</div><div>{L("الاسم", "Name")}</div>
          <div>{L("شهرياً / دكتور", "Monthly / doctor")}</div><div>{L("سنوياً / دكتور", "Yearly / doctor")}</div>
          <div>{L("المميزات", "Features")}</div>
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
              <div>{plan.seat_price_sar === null
                ? <span style={{ color: "#5c7096" }}>—</span>
                : <bdi>{fmtSar(plan.seat_price_sar)} SAR</bdi>}</div>
              <div>{plan.seat_price_yearly_sar === null
                ? <span style={{ color: "#5c7096" }}>—</span>
                : <bdi>{fmtSar(plan.seat_price_yearly_sar)} SAR</bdi>}</div>
              <div>
                <span className={plan.features_on === plan.features_total ? "badge success" : plan.features_on === 0 ? "badge neutral" : "badge"}
                  style={plan.features_on > 0 && plan.features_on < plan.features_total
                    ? { background: "rgba(42,111,151,.12)", color: "#3b82c4" } : undefined}>
                  <span className="num">{plan.features_on}</span>/<span className="num">{plan.features_total}</span>
                </span>
              </div>
              <div className="num">{plan.facilities_count}</div>
              <div>
                <span className={plan.is_active ? "badge success" : "badge neutral"}>
                  {plan.is_active ? L("فعّالة", "Active") : L("موقوفة", "Inactive")}
                </span>
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <button className="btn-row" disabled={busy === plan.id} onClick={() => setEditing(plan)}>{L("تعديل", "Edit")}</button>
                <button className="btn-row" disabled={busy === plan.id || catalog === null} onClick={() => setFeaturesOf(plan)}
                  title={L("اختر ما تُظهره هذه الباقة للدكتور", "Choose what this plan shows the doctor")}>
                  {L("المميزات", "Features")}
                </button>
                <button className={plan.is_active ? "btn-row warn" : "btn-row"} disabled={busy === plan.id} onClick={() => void toggleActive(plan)}>
                  {plan.is_active ? L("إيقاف", "Deactivate") : L("تفعيل", "Activate")}
                </button>
              </div>
            </div>
          ))
        )}
      </div>
      <p style={{ fontSize: 12.5, color: "#5c7096", margin: "10px 0 0" }}>
        {L("الفاتورة = عدد الدكاترة النشطين × تكلفة الدكتور + ضريبة 15% مفصولة · تعديل التكلفة لا يمس الفواتير الصادرة ويظهر فوراً في صفحة تسجيل المنشآت.",
           "Invoice = active doctors × cost per doctor + itemized 15% VAT · cost changes never touch issued invoices and appear immediately on the facility signup page.")}
      </p>
      <p style={{ fontSize: 12.5, color: "#5c7096", margin: "6px 0 0" }}>
        {L("«المميزات» تحدد ما يظهر للدكتور في هذه الباقة — الأساسية (تسجيل، مذكرة، بوابتان، نقل) مضمّنة دائماً ولا تُطفأ.",
           "“Features” controls what the doctor sees on this plan — the core (recording, note, both gates, upload) is always included and cannot be turned off.")}
      </p>
      {editing !== null ? (
        <PlanModal plan={editing === "new" ? null : editing} onClose={() => setEditing(null)}
          onDone={async () => { setEditing(null); await load(); }} />
      ) : null}
      {featuresOf !== null && catalog !== null ? (
        <FeaturesModal plan={featuresOf} catalog={catalog} onClose={() => setFeaturesOf(null)}
          onDone={async () => { setFeaturesOf(null); await load(); }} />
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
