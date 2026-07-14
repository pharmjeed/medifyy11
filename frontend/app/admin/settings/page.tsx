"use client";

/** الصفحة 8 — إعدادات المنشأة W-106/W-107/W-112: ترميز / ربط / قوالب عامة (FR-301/302 · DOC-06 §٣). */

import { useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { Field, Modal, SpecBadge, SpecBar, Tabs, fmtDateTime, useToast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { CodingSystemAdmin, IntegrationInfo, Template, TemplateSection } from "@/lib/types";

function apiErrorText(err: unknown): string {
  return err instanceof ApiError ? `${err.messageAr} (${err.code})` : "تعذر الاتصال بالخادم";
}

/* ===== تبويب «أنظمة الترميز» W-106 ===== */
const SYSTEM_META: Record<CodingSystemAdmin["system"], { display: string; usage: string }> = {
  ICD10AM: { display: "ICD-10-AM", usage: "التشخيصات — نظام التشخيص الأساسي، لا يُعطّل" },
  ACHI: { display: "ACHI", usage: "الإجراءات والمختبرات" },
  SBS: { display: "SBS", usage: "الفوترة السعودية الموحدة — أساس مطالبات NPHIES" },
  SFDA: { display: "SFDA", usage: "الأدوية والمستحضرات — سجل الأدوية السعودي GTIN" },
};

function CodingTab() {
  const toast = useToast();
  const [rows, setRows] = useState<CodingSystemAdmin[]>([]);
  const [loading, setLoading] = useState(true);
  const [busySystem, setBusySystem] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const body = await api<CodingSystemAdmin[]>("/settings/coding-systems");
      setRows(body.data);
    } catch (err) {
      toast(apiErrorText(err));
    } finally {
      setLoading(false);
    }
  }, [toast]);

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
        ? `فُعّل ${meta.display} — ينعكس على صياغة الإرشادات (FR-301)`
        : `أُلغي تفعيل ${meta.display} — ينعكس على صياغة الإرشادات (FR-301)`);
      await load();
    } catch (err) {
      // ICD10AM: الخادم يرفض التعطيل بـMDF-4031 — قيد CHECK في القاعدة هو الحكم
      toast(apiErrorText(err));
    } finally {
      setBusySystem(null);
    }
  };

  return (
    <>
      <div className="card" style={{ padding: 0 }}>
        {loading ? (
          <div className="grid-empty">جارٍ التحميل…</div>
        ) : rows.length === 0 ? (
          <div className="grid-empty">لا أنظمة ترميز مكوّنة</div>
        ) : (
          rows.map((row, i) => {
            const meta = SYSTEM_META[row.system];
            const locked = row.system === "ICD10AM";
            return (
              <div key={row.id} style={{
                display: "flex", alignItems: "center", gap: 14, padding: "14px 18px",
                borderTop: i > 0 ? "1px solid #EAF6F7" : "none",
              }}>
                <button
                  type="button"
                  role="switch"
                  aria-checked={row.is_active}
                  aria-label={`تبديل النظام ${meta.display}`}
                  className={row.is_active ? "switch on" : "switch"}
                  style={locked ? { opacity: 0.55, cursor: "not-allowed" } : undefined}
                  disabled={busySystem !== null}
                  onClick={() => void toggle(row)}
                >
                  <span className="knob" />
                </button>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <bdi style={{ fontWeight: 700, fontSize: 14, color: "#0A5C64" }}>{meta.display}</bdi>
                    <span style={{ fontSize: 12.5, color: "#5B7280" }}>الإصدار <bdi>{row.version}</bdi></span>
                    {locked ? (
                      <span className="badge warn">لا يُعطَّل — نظام التشخيص الأساسي (قرار مالك 2026-07-14)</span>
                    ) : null}
                  </div>
                  <div style={{ fontSize: 12.5, color: "#5B7280" }}>{meta.usage}</div>
                </div>
                <span className={row.is_active ? "badge success" : "badge neutral"}>
                  {row.is_active ? "نشط" : "غير نشط"}
                </span>
              </div>
            );
          })
        )}
      </div>
      <div className="info-box" style={{ marginTop: 14 }}>
        أثر الاختيار يظهر في كل إرشاد ترميزي (FR-301): تُصاغ الإرشادات بمصطلحات الأنظمة النشطة حصراً،
        ويُسمح بأكثر من نظام نشط (<bdi>coding_system_configs</bdi>).
      </div>
    </>
  );
}

/* ===== تبويب «الربط مع نظام المستشفى» W-107 ===== */
function IntegrationTab() {
  const toast = useToast();
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
      toast(apiErrorText(err));
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { void load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      const body: Record<string, unknown> = { endpoint_url: endpointUrl, mode };
      if (secret.trim() !== "") body["auth_secret"] = secret; // يُرسل فقط إن مُلئ
      await api("/settings/integration", { method: "PATCH", body });
      toast("حُفظت إعدادات الربط");
      setSecret("");
      await load();
    } catch (err) {
      toast(apiErrorText(err));
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    try {
      const body = await api<{ ok: boolean; tested_at: string }>("/settings/integration/test", { method: "POST" });
      toast(body.data.ok
        ? "نجح اختبار الاتصال — حُدّث last_test_at (FR-302)"
        : "فشل اختبار الاتصال (MDF-5052) — تحقق من نقطة النهاية");
      await load();
    } catch (err) {
      toast(apiErrorText(err));
    } finally {
      setTesting(false);
    }
  };

  if (loading) return <div className="grid-empty">جارٍ التحميل…</div>;
  if (info === null) return <div className="grid-empty">تعذر تحميل إعدادات الربط</div>;

  return (
    <>
      <div className="card pad24">
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: 0, flex: 1 }}>وجهة الرفع</h2>
          <span className="tech-badge">integration_configs</span>
          {info.last_test_ok === true ? (
            <span className="badge success">متصل</span>
          ) : info.last_test_ok === false ? (
            <span className="badge danger">غير متصل</span>
          ) : (
            <span className="badge neutral">لم يُختبر بعد</span>
          )}
        </div>

        <Field
          label="نقطة النهاية Endpoint"
          ltr
          placeholder="https://his.example.med.sa/fhir/R4"
          value={endpointUrl}
          onChange={(event) => setEndpointUrl(event.target.value)}
        />
        <Field
          label="مفتاح الربط"
          ltr
          type="password"
          placeholder={info.has_secret ? "•••••••• (محفوظ — يُرسل فقط إن مُلئ)" : "أدخل مفتاح الربط"}
          value={secret}
          onChange={(event) => setSecret(event.target.value)}
        />
        <p style={{ fontSize: 12.5, color: "#5B7280", margin: "4px 0 0" }}>
          مشفّر عموداً (<bdi>auth_secret_encrypted</bdi>) — لا يُعرض بعد الحفظ.
        </p>
        <label className="field-label" htmlFor="integration-mode">الوضع</label>
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
            {saving ? <span className="spinner" /> : null} حفظ الإعدادات
          </button>
          <button className="btn-secondary" onClick={() => void test()} disabled={testing}>
            {testing ? <><span className="spinner dark" /> جارٍ الاختبار…</> : "اختبار الاتصال"}
          </button>
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: 12.5, color: "#5B7280" }}>
            آخر اختبار: {info.last_test_at !== null ? fmtDateTime(info.last_test_at) : "—"} (<bdi>last_test_at</bdi>)
          </span>
        </div>
      </div>
      <div className="info-box" style={{ marginTop: 14 }}>
        الرفع أحادي الاتجاه بعد الاعتماد: حزمة <bdi>FHIR Bundle</bdi> تضم <bdi>Encounter</bdi> + <bdi>Composition (SOAP)</bdi> + <bdi>Condition[]</bdi> + <bdi>MedicationRequest[]</bdi> + <bdi>Procedure[]</bdi> بالرموز المعتمدة (DOC-05 §٦).
      </div>
    </>
  );
}

/* ===== تبويب «القوالب العامة» W-112 ===== */
const TEMPLATE_COLS = "2fr 1fr .7fr 1fr .9fr";
const ORIGIN_LABEL: Record<Template["origin"], string> = {
  system: "جاهز",
  reverse_built: "بناء عكسي",
};

const EMPTY_SECTION: TemplateSection = { section_key: "", title: "", instructions: "" };

function TemplatesTab() {
  const toast = useToast();
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
      toast(apiErrorText(err));
    } finally {
      setLoading(false);
    }
  }, [toast]);

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
      toast("أُنشئ القالب العام");
      setOpen(false);
      resetForm();
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.code === "MDF-4225") {
        setModalError("بنية ناقصة — أكمل مفتاح وعنوان وتعليمات كل قسم دون تكرار المفاتيح (MDF-4225)");
      } else {
        setModalError(apiErrorText(err));
      }
    } finally {
      setSaving(false);
    }
  };

  const archive = async (id: string) => {
    try {
      await api(`/templates/${id}`, { method: "DELETE" });
      toast("أُرشف القالب العام — بنية فقط دون محتوى سريري (DOC-06 §٣)");
      await load();
    } catch (err) {
      toast(apiErrorText(err));
    }
  };

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 12 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, margin: 0, flex: 1 }}>القوالب العامة للمنشأة</h2>
        <button className="btn h40" onClick={() => { resetForm(); setOpen(true); }}>+ قالب عام</button>
      </div>
      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: TEMPLATE_COLS }}>
          <div>القالب العام</div><div>التخصص</div><div>الأقسام</div><div>النوع</div><div>إجراء</div>
        </div>
        {loading ? (
          <div className="grid-empty">جارٍ التحميل…</div>
        ) : rows.length === 0 ? (
          <div className="grid-empty">لا قوالب عامة بعد — أنشئ الأول</div>
        ) : (
          rows.map((template, i) => (
            <div key={template.id} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: TEMPLATE_COLS }}>
              <div style={{ fontWeight: 700 }}>{template.name}</div>
              <div>{template.specialty ?? "—"}</div>
              <div className="num">{template.structure.sections.length}</div>
              <div><span className="badge neutral">{ORIGIN_LABEL[template.origin]}</span></div>
              <div><button className="btn-row neutral" onClick={() => void archive(template.id)}>أرشفة</button></div>
            </div>
          ))
        )}
      </div>
      <p style={{ fontSize: 12.5, color: "#5B7280", margin: "10px 0 0" }}>
        الأدمن يدير البنية دون رؤية محتوى سريري (DOC-06 §٣).
      </p>

      {open ? (
        <Modal title="قالب عام جديد" spec="W-112" onClose={() => setOpen(false)} wide>
          <Field label="اسم القالب" placeholder="مثال: باطنة — متابعة عامة SOAP" value={name} onChange={(event) => setName(event.target.value)} />
          <Field label="التخصص" placeholder="مثال: باطنة" value={specialty} onChange={(event) => setSpecialty(event.target.value)} />
          <Field label="نوع الزيارة" placeholder="مثال: متابعة" value={visitType} onChange={(event) => setVisitType(event.target.value)} />

          <label className="field-label">أقسام القالب</label>
          {sections.map((section, index) => (
            <div key={index} style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr 1.8fr auto", gap: 8, marginTop: index > 0 ? 8 : 0, alignItems: "center" }}>
              <input
                className="field mono"
                dir="ltr"
                placeholder="section_key"
                aria-label="مفتاح القسم"
                value={section.section_key}
                onChange={(event) => updateSection(index, { section_key: event.target.value })}
              />
              <input
                className="field"
                placeholder="العنوان"
                aria-label="عنوان القسم"
                value={section.title}
                onChange={(event) => updateSection(index, { title: event.target.value })}
              />
              <input
                className="field"
                placeholder="التعليمات"
                aria-label="تعليمات القسم"
                value={section.instructions}
                onChange={(event) => updateSection(index, { instructions: event.target.value })}
              />
              <button
                className="btn-row neutral"
                onClick={() => setSections((prev) => prev.filter((_, i) => i !== index))}
                disabled={sections.length === 1}
              >حذف</button>
            </div>
          ))}
          <button
            className="btn-ghost"
            style={{ marginTop: 8 }}
            onClick={() => setSections((prev) => [...prev, { ...EMPTY_SECTION }])}
          >+ إضافة قسم</button>

          {modalError !== null ? (
            <p style={{ color: "#C0392B", fontSize: 12.5, fontWeight: 700, margin: "12px 0 0" }}>{modalError}</p>
          ) : null}

          <div className="modal-actions">
            <button className="btn" onClick={() => void saveTemplate()} disabled={saving}>
              {saving ? <span className="spinner" /> : null} حفظ القالب العام
            </button>
            <button className="btn-neutral" onClick={() => setOpen(false)}>إلغاء</button>
          </div>
        </Modal>
      ) : null}
    </>
  );
}

/* ===== الصفحة ===== */
function SettingsInner() {
  const [tab, setTab] = useState<"coding" | "integration" | "templates">("coding");
  return (
    <>
      <SpecBar ids="W-106 · W-107 · W-112" desc="الصفحة 8 — تبويبات: ترميز / ربط / قوالب عامة" />
      <Tabs
        tabs={[
          { key: "coding", label: <>أنظمة الترميز <SpecBadge id="W-106" /></> },
          { key: "integration", label: <>الربط مع نظام المستشفى <SpecBadge id="W-107" /></> },
          { key: "templates", label: <>القوالب العامة <SpecBadge id="W-112" /></> },
        ]}
        active={tab}
        onChange={setTab}
      />
      {tab === "coding" ? <CodingTab /> : tab === "integration" ? <IntegrationTab /> : <TemplatesTab />}
    </>
  );
}

export default function SettingsPage() {
  return (
    <Shell title="إعدادات المنشأة">
      <main className="page-wrap narrow">
        <SettingsInner />
      </main>
    </Shell>
  );
}
