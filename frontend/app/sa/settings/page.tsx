"use client";

/** إعدادات الذكاء الاصطناعي (توجيه مالك 2026-08-01) — اختيار نموذج قوقل لكامل المنصة.
 *  القائمة تُجلب حيّة من Google API (أو كتالوج احتياطي)، والتبديل يسري فوراً دون نشر.
 *  التعديل لمالك المنصة حصراً (settings.write) وهو إجراء حسّاس (إعادة مصادقة TOTP). */

import { useCallback, useEffect, useMemo, useState } from "react";
import { SaShell } from "@/components/SaShell";
import { useToast } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import type { Lang } from "@/lib/i18n";
import { getSaAdmin, saApi, saCan } from "@/lib/sa";
import type { SaApiOptions } from "@/lib/sa";
import type { SaAiSettings } from "@/lib/types";

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

function apiErrorText(err: unknown, lang: Lang, L: LFn): string {
  return err instanceof ApiError ? `${err.text(lang)} (${err.code})` : L("تعذر الاتصال بالخادم", "Could not reach the server");
}

function EngineBadge({ engine, L }: { engine: string; L: LFn }) {
  const live = engine === "gemini";
  return (
    <span className={live ? "badge success" : "badge neutral"}>
      {live ? "Gemini" : engine === "mock" ? L("تجريبي (mock)", "Mock") : <bdi>{engine}</bdi>}
    </span>
  );
}

function SettingsInner() {
  const toast = useToast();
  const { L, lang } = useLang();
  const admin = getSaAdmin();
  const canWrite = saCan(admin, "settings.write");
  const [data, setData] = useState<SaAiSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [choice, setChoice] = useState<string | null>(null); // null = افتراضي البيئة
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const body = await saApi<SaAiSettings>("/settings/ai");
      setData(body.data);
      setChoice(body.data.selected_model);
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setLoading(false);
    }
  }, [toast, lang, L]);

  useEffect(() => { void load(); }, [load]);

  const visibleModels = useMemo(() => {
    if (data === null) return [];
    const q = filter.trim().toLowerCase();
    if (!q) return data.models;
    return data.models.filter((m) =>
      m.id.toLowerCase().includes(q) || m.display_name.toLowerCase().includes(q));
  }, [data, filter]);

  if (loading) return <p style={{ color: "#5c7096" }}>{L("جارٍ التحميل…", "Loading…")}</p>;
  if (data === null) return <p style={{ color: "#d94b4b" }}>{L("تعذر تحميل الإعدادات", "Could not load settings")}</p>;

  const dirty = choice !== data.selected_model;

  const save = async (model: string | null) => {
    setBusy(true);
    try {
      const body = await saSensitive<SaAiSettings>(L, "/settings/ai", {
        method: "PATCH",
        body: { gemini_model: model },
      });
      setData(body.data);
      setChoice(body.data.selected_model);
      toast(model === null
        ? L(`عاد النموذج إلى افتراضي البيئة (${body.data.effective_model})`, `Model reset to environment default (${body.data.effective_model})`)
        : L(`تم التبديل إلى ${body.data.effective_model} — يسري فوراً على التلخيص والتفريغ الحي`,
            `Switched to ${body.data.effective_model} — applies immediately to summarization and live transcription`));
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {/* الحالة الفعلية */}
      <div className="grid-table" style={{ marginBottom: 18 }}>
        <div className="grid-row" style={{ gridTemplateColumns: "1fr 1fr 1fr 1fr" }}>
          <div>
            <span style={{ display: "block", fontSize: 12.5, color: "#5c7096" }}>{L("النموذج الفعلي", "Effective model")}</span>
            <bdi className="num" style={{ fontWeight: 800 }}>{data.effective_model}</bdi>
          </div>
          <div>
            <span style={{ display: "block", fontSize: 12.5, color: "#5c7096" }}>{L("المصدر", "Source")}</span>
            {data.selected_model !== null
              ? <span className="badge" style={{ background: "#00c2b8", color: "#0c1a36", fontWeight: 800 }}>{L("اختيار المنصة", "Platform choice")}</span>
              : <span className="badge neutral">{L("افتراضي البيئة", "Environment default")}</span>}
          </div>
          <div>
            <span style={{ display: "block", fontSize: 12.5, color: "#5c7096" }}>{L("محرك التلخيص", "LLM engine")}</span>
            <EngineBadge engine={data.llm_engine} L={L} />
          </div>
          <div>
            <span style={{ display: "block", fontSize: 12.5, color: "#5c7096" }}>{L("محرك التفريغ", "STT engine")}</span>
            <EngineBadge engine={data.stt_engine} L={L} />
          </div>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, margin: 0, flex: 1 }}>{L("نماذج قوقل المتاحة", "Available Google models")}</h2>
        <span className={data.models_source === "live" ? "badge success" : "badge neutral"}>
          {data.models_source === "live" ? L("قائمة حيّة من Google", "Live from Google") : L("كتالوج احتياطي", "Fallback catalog")}
        </span>
      </div>

      <input className="field" placeholder={L("تصفية النماذج…", "Filter models…")} dir="ltr"
        value={filter} onChange={(event) => setFilter(event.target.value)} style={{ marginBottom: 10 }} />

      <div className="grid-table" role="radiogroup" aria-label={L("اختيار النموذج", "Model selection")}>
        {visibleModels.length === 0 ? (
          <div className="grid-empty">{L("لا نموذج يطابق التصفية", "No model matches the filter")}</div>
        ) : (
          visibleModels.map((model, i) => {
            const selected = choice === model.id;
            const isDefault = model.id === data.default_model;
            return (
              <label key={model.id} className={i % 2 ? "grid-row odd" : "grid-row"}
                style={{ gridTemplateColumns: "24px 1.4fr 2fr auto", cursor: canWrite ? "pointer" : "default", alignItems: "center" }}>
                <input type="radio" name="gemini-model" checked={selected} disabled={!canWrite || busy}
                  onChange={() => setChoice(model.id)} style={{ accentColor: "#00c2b8" }} />
                <div>
                  <bdi className="num" style={{ fontWeight: selected ? 800 : 600 }}>{model.id}</bdi>
                  {model.display_name && model.display_name !== model.id ? (
                    <span style={{ display: "block", fontSize: 12.5, color: "#5c7096" }}><bdi>{model.display_name}</bdi></span>
                  ) : null}
                </div>
                <div style={{ fontSize: 12.5, color: "#5c7096" }}>{model.description}</div>
                <div style={{ display: "flex", gap: 6 }}>
                  {isDefault ? <span className="badge neutral">{L("افتراضي البيئة", "Env default")}</span> : null}
                  {model.id === data.effective_model ? <span className="badge success">{L("الفعلي الآن", "Active now")}</span> : null}
                </div>
              </label>
            );
          })
        )}
      </div>

      {canWrite ? (
        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <button className="btn h40" disabled={busy || !dirty || choice === null} onClick={() => void save(choice)}>
            {busy ? <span className="spinner" /> : null} {L("حفظ الاختيار", "Save selection")}
          </button>
          <button className="btn-row warn" disabled={busy || data.selected_model === null} onClick={() => void save(null)}>
            {L("العودة لافتراضي البيئة", "Reset to environment default")}
          </button>
        </div>
      ) : (
        <p style={{ fontSize: 12.5, color: "#5c7096", marginTop: 12 }}>
          {L("تغيير النموذج لمالك المنصة حصراً — عرض فقط لدرجتك.", "Model changes are owner-only — read-only for your grade.")}
        </p>
      )}

      <p style={{ fontSize: 12.5, color: "#5c7096", margin: "12px 0 0" }}>
        {L("التبديل يسري فوراً على تلخيص الزيارات والتفريغ الحي في كل المنشآت دون إعادة نشر · إجراء حسّاس يتطلب رمز مصادقة حياً عند تفعيل 2FA · كل تغيير يُدوَّن في سجل المنصة.",
           "Switching applies immediately to visit summarization and live transcription across all facilities with no redeploy · sensitive action requiring a live authenticator code when 2FA is on · every change is recorded in the platform audit log.")}
      </p>
    </>
  );
}

export default function SaSettingsPage() {
  const { L } = useLang();
  return (
    <SaShell title={L("الذكاء الاصطناعي", "AI settings")}>
      <main className="page-wrap narrow">
        <SettingsInner />
      </main>
    </SaShell>
  );
}
