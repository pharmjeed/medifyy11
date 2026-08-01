"use client";

/** ملفات الأكواد المعتمدة (قرار مالك 2026-08-02) — نشر وتحديث السجل المرجعي للأكواد.
 *  لكل نظام (SBS/ICD10AM/ACHI/SFDA/GMDN): الحالة والأعداد والإصدارات، ورفع ملف جديد
 *  (xlsx من CHI أو CSV عام) بخطوتين: معاينة (dry-run) ثم «اعتماد ونشر» (حسّاس — TOTP).
 *  سجل فارغ لنظامٍ ما = لا تحقق لذلك النظام؛ التحميل يُفعّل التحقق فوراً في كل المنشآت. */

import { useCallback, useEffect, useState } from "react";
import { SaShell } from "@/components/SaShell";
import { useToast } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import type { Lang } from "@/lib/i18n";
import { getSaAdmin, saApi, saApiUpload, saCan } from "@/lib/sa";
import type { SaRegistryImportResult, SaRegistrySystem } from "@/lib/types";

type LFn = (ar: string, en: string) => string;

const SYSTEM_META: Record<SaRegistrySystem["system"], { ar: string; en: string; source_ar: string; source_en: string }> = {
  SBS: {
    ar: "الفوترة والخدمات — SBS", en: "Billing & services — SBS",
    source_ar: "يُنزَّل رسمياً من chi.gov.sa → Saudi Billing System",
    source_en: "Official download: chi.gov.sa → Saudi Billing System",
  },
  ICD10AM: {
    ar: "التشخيصات — ICD-10-AM", en: "Diagnoses — ICD-10-AM",
    source_ar: "مرخّص (IHACPA) — يُطلب عبر قنوات CHI/نفيس، لا يُنزّل حراً. لا يُستبدل بـ ICD-10-CM الأمريكي",
    source_en: "Licensed (IHACPA) — obtain via CHI/nphies channels; never substitute the US ICD-10-CM",
  },
  ACHI: {
    ar: "الإجراءات — ACHI", en: "Interventions — ACHI",
    source_ar: "مرخّص مثل ICD-10-AM — عبر قنوات CHI/نفيس",
    source_en: "Licensed like ICD-10-AM — via CHI/nphies channels",
  },
  SFDA: {
    ar: "الأدوية — SFDA", en: "Medications — SFDA",
    source_ar: "سجل الأدوية من هيئة الغذاء والدواء sfda.gov.sa",
    source_en: "Drug list from the Saudi FDA — sfda.gov.sa",
  },
  GMDN: {
    ar: "الأجهزة — GMDN", en: "Devices — GMDN",
    source_ar: "تسميات الأجهزة الطبية — عضوية GMDN Agency",
    source_en: "Medical device nomenclature — GMDN Agency membership",
  },
};

function apiErrorText(err: unknown, lang: Lang, L: LFn): string {
  if (err instanceof ApiError) {
    const detail = typeof err.details["error"] === "string" ? ` — ${err.details["error"]}` : "";
    return `${err.text(lang)}${detail} (${err.code})`;
  }
  return L("تعذر الاتصال بالخادم", "Could not reach the server");
}

function RegistryInner() {
  const toast = useToast();
  const { L, lang } = useLang();
  const admin = getSaAdmin();
  const canWrite = saCan(admin, "registry.write");

  const [systems, setSystems] = useState<SaRegistrySystem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  // نموذج الرفع
  const [formSystem, setFormSystem] = useState<SaRegistrySystem["system"]>("SBS");
  const [formVersion, setFormVersion] = useState("");
  const [formFile, setFormFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<SaRegistryImportResult | null>(null);

  const load = useCallback(async () => {
    try {
      const body = await saApi<{ systems: SaRegistrySystem[] }>("/registry");
      setSystems(body.data.systems);
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setLoading(false);
    }
  }, [toast, lang, L]);

  useEffect(() => { void load(); }, [load]);

  const buildForm = (dryRun: boolean): FormData | null => {
    if (formFile === null || formVersion.trim().length < 2) return null;
    const form = new FormData();
    form.append("file", formFile);
    form.append("system", formSystem);
    form.append("version", formVersion.trim());
    form.append("dry_run", dryRun ? "true" : "false");
    return form;
  };

  const runPreview = async () => {
    const form = buildForm(true);
    if (form === null) {
      toast(L("اختر الملف واكتب الإصدار أولاً", "Pick the file and enter the version first"));
      return;
    }
    setBusy(true);
    setPreview(null);
    try {
      const body = await saApiUpload<SaRegistryImportResult>("/registry/import", form);
      setPreview(body.data);
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setBusy(false);
    }
  };

  const publish = async () => {
    const form = buildForm(false);
    if (form === null) return;
    setBusy(true);
    try {
      let body: SaRegistryImportResult;
      try {
        body = (await saApiUpload<SaRegistryImportResult>("/registry/import", form)).data;
      } catch (err) {
        // إجراء حسّاس: عند تفعيل 2FA يطلب الخادم رمزاً حياً — نسأل ونعيد مرة واحدة
        if (err instanceof ApiError && err.code === "MDF-4015" && err.details["reason"] === "reauth_required") {
          const code = window.prompt(L("اعتماد ونشر — أدخل رمز المصادقة الحالي:", "Approve & publish — enter your current authenticator code:"));
          if (!code) { setBusy(false); return; }
          const retryForm = buildForm(false);
          if (retryForm === null) { setBusy(false); return; }
          body = (await saApiUpload<SaRegistryImportResult>("/registry/import", retryForm, code)).data;
        } else {
          throw err;
        }
      }
      if (body.systems) setSystems(body.systems);
      setPreview(null);
      setFormFile(null);
      setFormVersion("");
      toast(L(`اعتُمد ونُشر: ${body.inserted} كوداً جديداً و${body.updated} محدّثاً — ${body.system} ${body.version}. التحقق يسري فوراً في كل المنشآت.`,
              `Approved & published: ${body.inserted} new and ${body.updated} updated codes — ${body.system} ${body.version}. Validation applies immediately across all facilities.`));
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setBusy(false);
    }
  };

  const clearSystem = async (system: SaRegistrySystem["system"]) => {
    const sure = window.confirm(L(
      `إزالة سجل ${system} كاملاً؟ يتوقف التحقق لهذا النظام فوراً في كل المنشآت.`,
      `Remove the entire ${system} registry? Validation for this system stops immediately across all facilities.`,
    ));
    if (!sure) return;
    setBusy(true);
    try {
      let body: { systems: SaRegistrySystem[] };
      try {
        body = (await saApi<{ systems: SaRegistrySystem[] }>(`/registry/${system}`, { method: "DELETE" })).data;
      } catch (err) {
        if (err instanceof ApiError && err.code === "MDF-4015" && err.details["reason"] === "reauth_required") {
          const code = window.prompt(L("إجراء حسّاس — أدخل رمز المصادقة الحالي:", "Sensitive action — enter your current authenticator code:"));
          if (!code) { setBusy(false); return; }
          body = (await saApi<{ systems: SaRegistrySystem[] }>(`/registry/${system}`, { method: "DELETE", reauthCode: code })).data;
        } else {
          throw err;
        }
      }
      setSystems(body.systems);
      toast(L(`أُزيل سجل ${system} — توقف التحقق لهذا النظام`, `${system} registry removed — validation for it is now off`));
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <p style={{ color: "#5c7096" }}>{L("جارٍ التحميل…", "Loading…")}</p>;
  if (systems === null) return <p style={{ color: "#d94b4b" }}>{L("تعذر تحميل حالة السجل", "Could not load registry status")}</p>;

  return (
    <>
      {/* حالة الأنظمة */}
      <div className="grid-table" style={{ marginBottom: 18 }}>
        {systems.map((row, i) => {
          const meta = SYSTEM_META[row.system];
          return (
            <div key={row.system} className={i % 2 ? "grid-row odd" : "grid-row"}
              style={{ gridTemplateColumns: "1.6fr 1fr 1.2fr 1fr auto", alignItems: "center" }}>
              <div>
                <span style={{ display: "block", fontWeight: 700 }}>{L(meta.ar, meta.en)}</span>
                <span style={{ display: "block", fontSize: 12, color: "#5c7096" }}>{L(meta.source_ar, meta.source_en)}</span>
              </div>
              <div>
                {row.enforced
                  ? <span className="badge success">{L("التحقق مفعّل", "Validation on")}</span>
                  : <span className="badge neutral">{L("غير محمّل — لا تحقق", "Not loaded — no validation")}</span>}
              </div>
              <div style={{ fontSize: 13 }}>
                {row.total > 0 ? (
                  <>
                    <bdi className="num" style={{ fontWeight: 700 }}>{row.total.toLocaleString()}</bdi>{" "}
                    {L("كوداً", "codes")}
                    <span style={{ display: "block", fontSize: 12, color: "#5c7096" }}>
                      {L(`نشط ${row.active.toLocaleString()} · ملغى ${row.inactive.toLocaleString()}`,
                         `${row.active.toLocaleString()} active · ${row.inactive.toLocaleString()} retired`)}
                    </span>
                  </>
                ) : <span style={{ color: "#5c7096" }}>—</span>}
              </div>
              <div style={{ fontSize: 12.5, color: "#5c7096" }}>
                {row.versions.length > 0 ? <bdi className="ui">{row.versions.join(" · ")}</bdi> : "—"}
                {row.last_updated ? (
                  <span style={{ display: "block", fontSize: 11.5 }}>
                    {L("آخر تحديث:", "Last updated:")} <bdi className="num">{row.last_updated.slice(0, 10)}</bdi>
                  </span>
                ) : null}
              </div>
              <div>
                {canWrite && row.total > 0 ? (
                  <button className="btn-danger-outline" style={{ height: 32, fontSize: 12.5 }} disabled={busy}
                    onClick={() => void clearSystem(row.system)}>{L("إزالة", "Remove")}</button>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>

      {/* رفع ملف معتمد */}
      {canWrite ? (
        <div className="card" style={{ marginBottom: 14 }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 4px" }}>
            {L("نشر ملف أكواد معتمد", "Publish an approved code file")}
          </h2>
          <p style={{ fontSize: 12.5, color: "#5c7096", margin: "0 0 12px" }}>
            {L("ملف Excel الرسمي من CHI (تبويب Technical List يُكتشف تلقائياً) أو CSV عام بترويسة code/short_desc. خطوتان: معاينة ثم اعتماد ونشر.",
               "The official CHI Excel (Technical List tab auto-detected) or a generic CSV with code/short_desc headers. Two steps: preview, then approve & publish.")}
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1.4fr", gap: 10, alignItems: "end" }}>
            <div>
              <label className="field-label">{L("النظام", "System")}</label>
              <select className="field" value={formSystem} disabled={busy}
                onChange={(event) => { setFormSystem(event.target.value as SaRegistrySystem["system"]); setPreview(null); }}>
                {systems.map((row) => (
                  <option key={row.system} value={row.system}>{row.system} — {L(SYSTEM_META[row.system].ar, SYSTEM_META[row.system].en)}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="field-label">{L("الإصدار (يظهر على كل كود)", "Version (stamped on every code)")}</label>
              <input className="field" dir="ltr" placeholder='SBS V2.0' value={formVersion} disabled={busy}
                onChange={(event) => { setFormVersion(event.target.value); setPreview(null); }} />
            </div>
            <div>
              <label className="field-label">{L("الملف (xlsx أو csv)", "File (xlsx or csv)")}</label>
              <input className="field" type="file" accept=".xlsx,.xlsm,.csv" disabled={busy}
                onChange={(event) => { setFormFile(event.target.files?.[0] ?? null); setPreview(null); }} />
            </div>
          </div>

          {preview !== null ? (
            <div style={{ background: "#e6f7f4", border: "1px solid #8fe0da", borderRadius: 10, padding: "10px 14px", marginTop: 12, fontSize: 13.5 }}>
              {L(`معاينة ${preview.system} ${preview.version}: سيُدخل `, `Preview ${preview.system} ${preview.version}: will insert `)}
              <bdi className="num" style={{ fontWeight: 800 }}>{preview.inserted.toLocaleString()}</bdi>
              {L(" كوداً جديداً ويحدّث ", " new codes and update ")}
              <bdi className="num" style={{ fontWeight: 800 }}>{preview.updated.toLocaleString()}</bdi>
              {L(" قائماً — لم يُكتب شيء بعد.", " existing ones — nothing has been written yet.")}
            </div>
          ) : null}

          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button className="btn-secondary h40" disabled={busy || formFile === null || formVersion.trim().length < 2}
              onClick={() => void runPreview()}>
              {busy ? <span className="spinner dark" /> : null} {L("معاينة (بلا كتابة)", "Preview (no write)")}
            </button>
            <button className="btn h40" disabled={busy || preview === null}
              onClick={() => void publish()}>
              {busy ? <span className="spinner" /> : null} {L("اعتماد ونشر", "Approve & publish")}
            </button>
          </div>
        </div>
      ) : (
        <p style={{ fontSize: 12.5, color: "#5c7096" }}>
          {L("نشر ملفات الأكواد لمالك المنصة حصراً — عرض فقط لدرجتك.", "Publishing code files is owner-only — read-only for your grade.")}
        </p>
      )}

      <p style={{ fontSize: 12.5, color: "#5c7096", margin: 0 }}>
        {L("النشر يسري فوراً على اقتراحات الذكاء وتعديل الدكاترة وبوابة الاعتماد ② في كل المنشآت · الأكواد الملغاة في الملف تُعلَّم ببديلها ولا تمر من الاعتماد · إجراء حسّاس يتطلب رمز مصادقة حياً عند تفعيل 2FA · كل نشر أو إزالة يُدوَّن في سجل المنصة.",
           "Publishing applies immediately to AI suggestions, clinician code edits, and approval gate 2 across all facilities · retired codes are flagged with their replacement and blocked at approval · sensitive action requiring a live authenticator code when 2FA is on · every publish or removal is recorded in the platform audit log.")}
      </p>
    </>
  );
}

export default function SaRegistryPage() {
  const { L } = useLang();
  return (
    <SaShell title={L("ملفات الأكواد المعتمدة", "Approved code files")}>
      <main className="page-wrap">
        <RegistryInner />
      </main>
    </SaShell>
  );
}
