"use client";

/** الصفحة 8 — إعدادات المنشأة W-106/W-107/W-112: ترميز / ربط / قوالب عامة (FR-301/302 · DOC-06 §٣). */

import { useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { Field, Modal, SpecBadge, SpecBar, Tabs, fmtDateTime, useToast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import type { Lang } from "@/lib/i18n";
import type { CodingSystemAdmin, IntegrationInfo, Template, TemplateSection } from "@/lib/types";

function apiErrorText(err: unknown, lang: Lang): string {
  if (err instanceof ApiError) return `${err.text(lang)} (${err.code})`;
  return lang === "ar" ? "تعذر الاتصال بالخادم" : "Could not reach the server";
}

/* ===== تبويب «أنظمة الترميز» W-106 ===== */
const SYSTEM_META: Record<CodingSystemAdmin["system"], { display: string; usage: { ar: string; en: string } }> = {
  ICD10AM: {
    display: "ICD-10-AM",
    usage: { ar: "التشخيصات — نظام التشخيص الأساسي، لا يُعطّل", en: "Diagnoses — primary diagnosis system, cannot be disabled" },
  },
  ACHI: {
    display: "ACHI",
    usage: { ar: "الإجراءات والمختبرات", en: "Procedures and laboratory" },
  },
  SBS: {
    display: "SBS",
    usage: { ar: "الفوترة السعودية الموحدة — أساس مطالبات NPHIES", en: "Saudi unified billing — the basis of NPHIES claims" },
  },
  SFDA: {
    display: "SFDA",
    usage: { ar: "الأدوية والمستحضرات — سجل الأدوية السعودي GTIN", en: "Medications and preparations — Saudi GTIN drug registry" },
  },
};

function CodingTab() {
  const toast = useToast();
  const { L, lang } = useLang();
  const [rows, setRows] = useState<CodingSystemAdmin[]>([]);
  const [loading, setLoading] = useState(true);
  const [busySystem, setBusySystem] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const body = await api<CodingSystemAdmin[]>("/settings/coding-systems");
      setRows(body.data);
    } catch (err) {
      toast(apiErrorText(err, lang));
    } finally {
      setLoading(false);
    }
  }, [toast, lang]);

  useEffect(() => { void load(); }, [load]);

  const toggle = async (row: CodingSystemAdmin) => {
    const meta = SYSTEM_META[row.system];
    setBusySystem(row.system);
    try {
      await api("/settings/coding-systems", {
        method: "PATCH",
        body: { systems: { [row.system]: !row.is_active } },
      });
      toast(!row.is_active
        ? L(`فُعّل ${meta.display} — ينعكس على صياغة الإرشادات (FR-301)`,
            `${meta.display} enabled — reflected in guidance wording (FR-301)`)
        : L(`أُلغي تفعيل ${meta.display} — ينعكس على صياغة الإرشادات (FR-301)`,
            `${meta.display} disabled — reflected in guidance wording (FR-301)`));
      await load();
    } catch (err) {
      // ICD10AM: الخادم يرفض التعطيل بـMDF-4031 — قيد CHECK في القاعدة هو الحكم
      toast(apiErrorText(err, lang));
    } finally {
      setBusySystem(null);
    }
  };

  return (
    <>
      <div className="card" style={{ padding: 0 }}>
        {loading ? (
          <div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div>
        ) : rows.length === 0 ? (
          <div className="grid-empty">{L("لا أنظمة ترميز مكوّنة", "No coding systems configured")}</div>
        ) : (
          rows.map((row, i) => {
            const meta = SYSTEM_META[row.system];
            const locked = row.system === "ICD10AM";
            return (
              <div key={row.id} style={{
                display: "flex", alignItems: "center", gap: 14, padding: "14px 18px",
                borderTop: i > 0 ? "1px solid #d6f5f2" : "none",
              }}>
                <button
                  type="button"
                  role="switch"
                  aria-checked={row.is_active}
                  aria-label={L(`تبديل النظام ${meta.display}`, `Toggle ${meta.display} system`)}
                  className={row.is_active ? "switch on" : "switch"}
                  style={locked ? { opacity: 0.55, cursor: "not-allowed" } : undefined}
                  disabled={busySystem !== null}
                  onClick={() => void toggle(row)}
                >
                  <span className="knob" />
                </button>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <bdi style={{ fontWeight: 700, fontSize: 14, color: "#005a55" }}>{meta.display}</bdi>
                    <span style={{ fontSize: 12.5, color: "#5c7096" }}>{L("الإصدار", "Version")} <bdi>{row.version}</bdi></span>
                    {locked ? (
                      <span className="badge warn">
                        {L("لا يُعطَّل — نظام التشخيص الأساسي (قرار مالك 2026-07-14)",
                           "Cannot be disabled — primary diagnosis system (owner decision 2026-07-14)")}
                      </span>
                    ) : null}
                  </div>
                  <div style={{ fontSize: 12.5, color: "#5c7096" }}>{L(meta.usage.ar, meta.usage.en)}</div>
                </div>
                <span className={row.is_active ? "badge success" : "badge neutral"}>
                  {row.is_active ? L("نشط", "Active") : L("غير نشط", "Inactive")}
                </span>
              </div>
            );
          })
        )}
      </div>
      <div className="info-box" style={{ marginTop: 14 }}>
        {L("أثر الاختيار يظهر في كل إرشاد ترميزي (FR-301): تُصاغ الإرشادات بمصطلحات الأنظمة النشطة حصراً، ويُسمح بأكثر من نظام نشط",
           "The selection affects every coding guidance item (FR-301): guidance is phrased strictly in the terminology of the active systems, and more than one active system is allowed")}{" "}
        (<bdi>coding_system_configs</bdi>).
      </div>
    </>
  );
}

/* ===== تبويب «الربط مع نظام المستشفى» W-107 ===== */
function IntegrationTab() {
  const toast = useToast();
  const { L, lang } = useLang();
  const [info, setInfo] = useState<IntegrationInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [endpointUrl, setEndpointUrl] = useState("");
  const [secret, setSecret] = useState("");
  const [mode, setMode] = useState<"test" | "live">("test");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  const load = useCallback(async () => {
    try {
      const body = await api<IntegrationInfo>("/settings/integration");
      setInfo(body.data);
      setEndpointUrl(body.data.endpoint_url ?? "");
      setMode(body.data.mode);
    } catch (err) {
      toast(apiErrorText(err, lang));
    } finally {
      setLoading(false);
    }
  }, [toast, lang]);

  useEffect(() => { void load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      const body: Record<string, unknown> = { endpoint_url: endpointUrl, mode };
      if (secret.trim() !== "") body["auth_secret"] = secret; // يُرسل فقط إن مُلئ
      await api("/settings/integration", { method: "PATCH", body });
      toast(L("حُفظت إعدادات الربط", "Integration settings saved"));
      setSecret("");
      await load();
    } catch (err) {
      toast(apiErrorText(err, lang));
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    try {
      const body = await api<{ ok: boolean; tested_at: string }>("/settings/integration/test", { method: "POST" });
      toast(body.data.ok
        ? L("نجح اختبار الاتصال — حُدّث last_test_at (FR-302)", "Connection test passed — last_test_at updated (FR-302)")
        : L("فشل اختبار الاتصال (MDF-5052) — تحقق من نقطة النهاية", "Connection test failed (MDF-5052) — check the endpoint"));
      await load();
    } catch (err) {
      toast(apiErrorText(err, lang));
    } finally {
      setTesting(false);
    }
  };

  if (loading) return <div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div>;
  if (info === null) return <div className="grid-empty">{L("تعذر تحميل إعدادات الربط", "Could not load integration settings")}</div>;

  return (
    <>
      <div className="card pad24">
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: 0, flex: 1 }}>{L("وجهة الرفع", "Upload destination")}</h2>
          <span className="tech-badge">integration_configs</span>
          {info.last_test_ok === true ? (
            <span className="badge success">{L("متصل", "Connected")}</span>
          ) : info.last_test_ok === false ? (
            <span className="badge danger">{L("غير متصل", "Disconnected")}</span>
          ) : (
            <span className="badge neutral">{L("لم يُختبر بعد", "Not tested yet")}</span>
          )}
        </div>

        <Field
          label={L("نقطة النهاية Endpoint", "Endpoint")}
          ltr
          placeholder="https://his.example.med.sa/fhir/R4"
          value={endpointUrl}
          onChange={(event) => setEndpointUrl(event.target.value)}
        />
        <Field
          label={L("مفتاح الربط", "Integration key")}
          ltr
          type="password"
          placeholder={info.has_secret
            ? L("•••••••• (محفوظ — يُرسل فقط إن مُلئ)", "•••••••• (saved — sent only if filled)")
            : L("أدخل مفتاح الربط", "Enter the integration key")}
          value={secret}
          onChange={(event) => setSecret(event.target.value)}
        />
        <p style={{ fontSize: 12.5, color: "#5c7096", margin: "4px 0 0" }}>
          {L("مشفّر عموداً", "Column-level encrypted")} (<bdi>auth_secret_encrypted</bdi>) {L("— لا يُعرض بعد الحفظ.", "— never displayed after saving.")}
        </p>
        <label className="field-label" htmlFor="integration-mode">{L("الوضع", "Mode")}</label>
        <select
          id="integration-mode"
          className="field mono"
          dir="ltr"
          value={mode}
          onChange={(event) => setMode(event.target.value === "live" ? "live" : "test")}
        >
          <option value="test">test</option>
          <option value="live">live</option>
        </select>

        <div className="modal-actions">
          <button className="btn" onClick={() => void save()} disabled={saving}>
            {saving ? <span className="spinner" /> : null} {L("حفظ الإعدادات", "Save settings")}
          </button>
          <button className="btn-secondary" onClick={() => void test()} disabled={testing}>
            {testing ? <><span className="spinner dark" /> {L("جارٍ الاختبار…", "Testing…")}</> : L("اختبار الاتصال", "Test connection")}
          </button>
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: 12.5, color: "#5c7096" }}>
            {L("آخر اختبار:", "Last test:")} {info.last_test_at !== null ? fmtDateTime(info.last_test_at) : "—"} (<bdi>last_test_at</bdi>)
          </span>
        </div>
      </div>
      <div className="info-box" style={{ marginTop: 14 }}>
        {L("الرفع أحادي الاتجاه بعد الاعتماد: حزمة", "Upload is one-way after approval: a")} <bdi>FHIR Bundle</bdi> {L("تضم", "containing")} <bdi>Encounter</bdi> + <bdi>Composition (SOAP)</bdi> + <bdi>Condition[]</bdi> + <bdi>MedicationRequest[]</bdi> + <bdi>Procedure[]</bdi> {L("بالرموز المعتمدة (DOC-05 §٦).", "with the approved codes (DOC-05 §6).")}
      </div>
    </>
  );
}

/* ===== تبويب «القوالب العامة» W-112 ===== */
const TEMPLATE_COLS = "2fr 1fr .7fr 1fr .9fr";
const ORIGIN_LABEL: Record<Template["origin"], { ar: string; en: string }> = {
  system: { ar: "جاهز", en: "Built-in" },
  reverse_built: { ar: "بناء عكسي", en: "Reverse build" },
};

const EMPTY_SECTION: TemplateSection = { section_key: "", title: "", instructions: "" };

function TemplatesTab() {
  const toast = useToast();
  const { L, lang } = useLang();
  const [rows, setRows] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [specialty, setSpecialty] = useState("");
  const [visitType, setVisitType] = useState("");
  const [sections, setSections] = useState<TemplateSection[]>([{ ...EMPTY_SECTION }]);
  const [modalError, setModalError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const body = await api<Template[]>("/templates");
      // الأدمن يرى العامة فقط — بنية دون محتوى سريري (DOC-06 §٣)
      setRows(body.data.filter((template) => !template.is_personal && template.archived_at === null));
    } catch (err) {
      toast(apiErrorText(err, lang));
    } finally {
      setLoading(false);
    }
  }, [toast, lang]);

  useEffect(() => { void load(); }, [load]);

  const resetForm = () => {
    setName("");
    setSpecialty("");
    setVisitType("");
    setSections([{ ...EMPTY_SECTION }]);
    setModalError(null);
  };

  const updateSection = (index: number, patch: Partial<TemplateSection>) => {
    setSections((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  const saveTemplate = async () => {
    setSaving(true);
    setModalError(null);
    try {
      await api("/templates", {
        method: "POST",
        body: {
          scope: "facility",
          origin: "system",
          name,
          specialty,
          visit_type: visitType,
          structure: { sections },
        },
      });
      toast(L("أُنشئ القالب العام", "Shared template created"));
      setOpen(false);
      resetForm();
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.code === "MDF-4225") {
        setModalError(L("بنية ناقصة — أكمل مفتاح وعنوان وتعليمات كل قسم دون تكرار المفاتيح (MDF-4225)",
                        "Incomplete structure — complete the key, title, and instructions of every section without duplicate keys (MDF-4225)"));
      } else {
        setModalError(apiErrorText(err, lang));
      }
    } finally {
      setSaving(false);
    }
  };

  const archive = async (id: string) => {
    try {
      await api(`/templates/${id}`, { method: "DELETE" });
      toast(L("أُرشف القالب العام — بنية فقط دون محتوى سريري (DOC-06 §٣)",
              "Shared template archived — structure only, no clinical content (DOC-06 §3)"));
      await load();
    } catch (err) {
      toast(apiErrorText(err, lang));
    }
  };

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 12 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, margin: 0, flex: 1 }}>{L("القوالب العامة للمنشأة", "Facility shared templates")}</h2>
        <button className="btn h40" onClick={() => { resetForm(); setOpen(true); }}>{L("+ قالب عام", "+ Shared template")}</button>
      </div>
      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: TEMPLATE_COLS }}>
          <div>{L("القالب العام", "Shared template")}</div><div>{L("التخصص", "Specialty")}</div><div>{L("الأقسام", "Sections")}</div><div>{L("النوع", "Type")}</div><div>{L("إجراء", "Action")}</div>
        </div>
        {loading ? (
          <div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div>
        ) : rows.length === 0 ? (
          <div className="grid-empty">{L("لا قوالب عامة بعد — أنشئ الأول", "No shared templates yet — create the first one")}</div>
        ) : (
          rows.map((template, i) => (
            <div key={template.id} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: TEMPLATE_COLS }}>
              <div style={{ fontWeight: 700 }}>{template.name}</div>
              <div>{template.specialty ?? "—"}</div>
              <div className="num">{template.structure.sections.length}</div>
              <div><span className="badge neutral">{L(ORIGIN_LABEL[template.origin].ar, ORIGIN_LABEL[template.origin].en)}</span></div>
              <div><button className="btn-row neutral" onClick={() => void archive(template.id)}>{L("أرشفة", "Archive")}</button></div>
            </div>
          ))
        )}
      </div>
      <p style={{ fontSize: 12.5, color: "#5c7096", margin: "10px 0 0" }}>
        {L("الأدمن يدير البنية دون رؤية محتوى سريري (DOC-06 §٣).", "The admin manages structure without seeing clinical content (DOC-06 §3).")}
      </p>

      {open ? (
        <Modal title={L("قالب عام جديد", "New shared template")} spec="W-112" onClose={() => setOpen(false)} wide>
          <Field label={L("اسم القالب", "Template name")} placeholder={L("مثال: باطنة — متابعة عامة SOAP", "e.g. Internal medicine — general follow-up SOAP")} value={name} onChange={(event) => setName(event.target.value)} />
          <Field label={L("التخصص", "Specialty")} placeholder={L("مثال: باطنة", "e.g. Internal medicine")} value={specialty} onChange={(event) => setSpecialty(event.target.value)} />
          <Field label={L("نوع الزيارة", "Visit type")} placeholder={L("مثال: متابعة", "e.g. Follow-up")} value={visitType} onChange={(event) => setVisitType(event.target.value)} />

          <label className="field-label">{L("أقسام القالب", "Template sections")}</label>
          {sections.map((section, index) => (
            <div key={index} style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr 1.8fr auto", gap: 8, marginTop: index > 0 ? 8 : 0, alignItems: "center" }}>
              <input
                className="field mono"
                dir="ltr"
                placeholder="section_key"
                aria-label={L("مفتاح القسم", "Section key")}
                value={section.section_key}
                onChange={(event) => updateSection(index, { section_key: event.target.value })}
              />
              <input
                className="field"
                placeholder={L("العنوان", "Title")}
                aria-label={L("عنوان القسم", "Section title")}
                value={section.title}
                onChange={(event) => updateSection(index, { title: event.target.value })}
              />
              <input
                className="field"
                placeholder={L("التعليمات", "Instructions")}
                aria-label={L("تعليمات القسم", "Section instructions")}
                value={section.instructions}
                onChange={(event) => updateSection(index, { instructions: event.target.value })}
              />
              <button
                className="btn-row neutral"
                onClick={() => setSections((prev) => prev.filter((_, i) => i !== index))}
                disabled={sections.length === 1}
              >{L("حذف", "Remove")}</button>
            </div>
          ))}
          <button
            className="btn-ghost"
            style={{ marginTop: 8 }}
            onClick={() => setSections((prev) => [...prev, { ...EMPTY_SECTION }])}
          >{L("+ إضافة قسم", "+ Add section")}</button>

          {modalError !== null ? (
            <p style={{ color: "#d94b4b", fontSize: 12.5, fontWeight: 700, margin: "12px 0 0" }}>{modalError}</p>
          ) : null}

          <div className="modal-actions">
            <button className="btn" onClick={() => void saveTemplate()} disabled={saving}>
              {saving ? <span className="spinner" /> : null} {L("حفظ القالب العام", "Save shared template")}
            </button>
            <button className="btn-neutral" onClick={() => setOpen(false)}>{L("إلغاء", "Cancel")}</button>
          </div>
        </Modal>
      ) : null}
    </>
  );
}

/* ===== الصفحة ===== */
function SettingsInner() {
  const { L } = useLang();
  const [tab, setTab] = useState<"coding" | "integration" | "templates">("coding");
  return (
    <>
      <SpecBar ids="W-106 · W-107 · W-112" desc={L("الصفحة 8 — تبويبات: ترميز / ربط / قوالب عامة", "Page 8 — tabs: coding / integration / shared templates")} />
      <Tabs
        tabs={[
          { key: "coding", label: <>{L("أنظمة الترميز", "Coding systems")} <SpecBadge id="W-106" /></> },
          { key: "integration", label: <>{L("الربط مع نظام المستشفى", "Hospital system integration")} <SpecBadge id="W-107" /></> },
          { key: "templates", label: <>{L("القوالب العامة", "Shared templates")} <SpecBadge id="W-112" /></> },
        ]}
        active={tab}
        onChange={setTab}
      />
      {tab === "coding" ? <CodingTab /> : tab === "integration" ? <IntegrationTab /> : <TemplatesTab />}
    </>
  );
}

export default function SettingsPage() {
  const { L } = useLang();
  return (
    <Shell title={L("إعدادات المنشأة", "Facility settings")}>
      <main className="page-wrap narrow">
        <SettingsInner />
      </main>
    </Shell>
  );
}
