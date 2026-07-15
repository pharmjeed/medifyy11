"use client";

/** الصفحة 13 — القوالب: W-203 (القائمة) + W-204 (المنشئ العكسي) + W-205 (المعاينة والحفظ). */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import type { Template, TemplateSection } from "@/lib/types";
import { Shell } from "@/components/Shell";
import { Modal, SpecBadge, SpecBar, useErrorScreen, useToast } from "@/components/ui";

type View = "list" | "builder" | "preview";

interface GeneratedTemplate {
  name: string;
  structure: { sections: TemplateSection[] };
}

interface PreviewSection {
  section_key: string;
  content: string;
}

const GOLD_BADGE = { background: "rgba(201,162,39,.15)", color: "#C9A227", border: "1px solid #C9A227" } as const;

function SectionKeyBox({ sectionKey }: { sectionKey: string }) {
  return (
    <span style={{
      width: 30, height: 30, borderRadius: 8, background: "#0A5C64", color: "#fff",
      display: "inline-flex", alignItems: "center", justifyContent: "center", fontWeight: 800, flexShrink: 0,
    }}>
      <bdi className="ui">{sectionKey}</bdi>
    </span>
  );
}

function TemplatesInner() {
  const toast = useToast();
  const showError = useErrorScreen();
  const { L, lang } = useLang();

  const [view, setView] = useState<View>("list");
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [structureTpl, setStructureTpl] = useState<Template | null>(null);

  // W-204 — المنشئ العكسي
  const [sampleText, setSampleText] = useState("");
  const [styleText, setStyleText] = useState("");
  const [building, setBuilding] = useState(false);

  // W-205 — المعاينة والحفظ
  const [generated, setGenerated] = useState<GeneratedTemplate | null>(null);
  const [runSections, setRunSections] = useState<PreviewSection[] | null>(null);
  const [running, setRunning] = useState(false);
  const [tplName, setTplName] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const body = await api<Template[]>("/templates");
      setTemplates(body.data);
    } catch (err) {
      showError(err);
    }
  }, [showError]);

  useEffect(() => { void load(); }, [load]);

  const systemTemplates = (templates ?? []).filter((tpl) => !tpl.is_personal);
  const personalTemplates = (templates ?? []).filter((tpl) => tpl.is_personal);

  const setDefault = async (tpl: Template) => {
    if (!tpl.is_personal) {
      toast(L("التعيين الافتراضي متاح لقوالبك الشخصية", "Default assignment is available for your personal templates only"));
      return;
    }
    try {
      await api(`/templates/${tpl.id}/default`, { method: "PATCH" });
      toast(L("عُيّن قالباً افتراضياً (FR-505)", "Set as default template (FR-505)"));
      void load();
    } catch (err) {
      showError(err);
    }
  };

  const removeTpl = async (tpl: Template) => {
    try {
      await api(`/templates/${tpl.id}`, { method: "DELETE" });
      toast(L("حُذف القالب الشخصي (FR-504)", "Personal template deleted (FR-504)"));
      void load();
    } catch (err) {
      showError(err);
    }
  };

  const generate = async () => {
    if (sampleText.trim() === "" || styleText.trim() === "") {
      toast(L("أدخل نص المثال وطريقة التلخيص أولاً (FR-502)", "Enter the sample text and summarization style first (FR-502)"));
      return;
    }
    setBuilding(true);
    try {
      const body = await api<GeneratedTemplate>("/templates/reverse-build", {
        method: "POST",
        body: { sample_text: sampleText, summarization_style: styleText },
      });
      setGenerated(body.data);
      setTplName(body.data.name.trim() !== "" ? body.data.name : L("قالب عكسي جديد", "New reverse-built template"));
      setRunSections(null);
      setSaveError(null);
      setView("preview");
    } catch (err) {
      if (err instanceof ApiError && err.code === "MDF-5034") {
        toast(`${err.text(lang)} — ${L("أعد المحاولة", "please retry")} (MDF-5034)`);
      } else {
        showError(err);
      }
    } finally {
      setBuilding(false);
    }
  };

  const runPreview = async () => {
    if (generated === null) return;
    setRunning(true);
    try {
      const body = await api<{ sections: PreviewSection[] }>("/templates/preview", {
        method: "POST",
        body: { structure: generated.structure },
      });
      setRunSections(body.data.sections);
    } catch (err) {
      if (err instanceof ApiError && err.code === "MDF-4225") {
        setSaveError(`${L("بنية ناقصة — حدد النقص:", "Incomplete structure — missing:")} ${err.text(lang)}`);
      } else {
        showError(err);
      }
    } finally {
      setRunning(false);
    }
  };

  const save = async () => {
    if (generated === null) return;
    if (tplName.trim() === "") {
      toast(L("أدخل اسم القالب", "Enter a template name"));
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      await api("/templates", {
        method: "POST",
        body: {
          name: tplName.trim(),
          structure: generated.structure,
          origin: "reverse_built",
          source_sample_text: sampleText,
        },
      });
      toast(L("حُفظ القالب — origin: reverse_built، جاهز لأي زيارة قادمة (FR-504)",
              "Template saved — origin: reverse_built, ready for any upcoming visit (FR-504)"));
      setView("list");
      setGenerated(null);
      setRunSections(null);
      setSampleText("");
      setStyleText("");
      void load();
    } catch (err) {
      if (err instanceof ApiError && err.code === "MDF-4225") {
        setSaveError(`${L("بنية ناقصة — حدد النقص:", "Incomplete structure — missing:")} ${err.text(lang)}`);
      } else {
        showError(err);
      }
    } finally {
      setSaving(false);
    }
  };

  const renderCard = (tpl: Template) => (
    <div
      key={tpl.id}
      className="card"
      style={{
        display: "flex", flexDirection: "column", gap: 10,
        border: tpl.is_default ? "1.5px solid #C9A227" : undefined,
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
        <strong style={{ flex: 1, fontSize: 15, lineHeight: 1.6 }}>{tpl.name}</strong>
        <button
          type="button"
          title={L("تعيين افتراضي (FR-505)", "Set as default (FR-505)")}
          aria-label={L("تعيين افتراضي (FR-505)", "Set as default (FR-505)")}
          onClick={() => void setDefault(tpl)}
          style={{
            border: "none", background: "none", cursor: "pointer", padding: 0,
            fontSize: 20, lineHeight: 1, color: tpl.is_default ? "#C9A227" : "#5B7280",
          }}
        >
          {tpl.is_default ? "★" : "☆"}
        </button>
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {tpl.specialty !== null ? <span className="badge neutral">{tpl.specialty}</span> : null}
        {tpl.visit_type !== null ? <span className="badge neutral">{tpl.visit_type}</span> : null}
        <span className="badge neutral"><span className="num">{tpl.structure.sections.length}</span> {L("أقسام", "sections")}</span>
        {tpl.origin === "reverse_built" ? <span className="badge" style={GOLD_BADGE}>{L("بناء عكسي", "Reverse build")}</span> : null}
        {tpl.is_default ? <span className="badge" style={GOLD_BADGE}>{L("الافتراضي", "Default")}</span> : null}
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: "auto" }}>
        <button className="btn-row" onClick={() => setStructureTpl(tpl)}>{L("معاينة البنية", "Preview structure")}</button>
        {tpl.is_personal ? (
          <button className="btn-row neutral" onClick={() => void removeTpl(tpl)}>{L("حذف", "Delete")}</button>
        ) : null}
      </div>
    </div>
  );

  /* ===== W-203 — القائمة ===== */
  if (view === "list") {
    return (
      <>
        <SpecBar ids="W-203 · W-204 · W-205" desc={L("الصفحة 13 — القائمة + المنشئ العكسي (إدخال ← معاينة/حفظ)", "Page 13 — list + reverse builder (input → preview/save)")} />
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 18 }}>
          <div style={{ flex: 1, minWidth: 240 }}>
            <h1 className="page-title" style={{ marginBottom: 2 }}>{L("قوالب التلخيص", "Summary templates")}</h1>
            <p className="page-desc" style={{ margin: 0 }}>{L("الاختيار إلزامي قبل بدء أي تسجيل (FR-501)", "Selecting a template is required before starting any recording (FR-501)")}</p>
          </div>
          <button className="btn" onClick={() => setView("builder")}>{L("+ قالب جديد عكسي", "+ New reverse-built template")}</button>
        </div>

        <h2 style={{ fontSize: 16, fontWeight: 800, margin: "0 0 10px" }}>{L("قوالب المنشأة الجاهزة", "Facility preset templates")}</h2>
        {templates === null ? (
          <div className="card" style={{ textAlign: "center", color: "#5B7280" }}>{L("جارٍ التحميل…", "Loading…")}</div>
        ) : systemTemplates.length === 0 ? (
          <div className="card" style={{ textAlign: "center", color: "#5B7280" }}>{L("لا قوالب جاهزة", "No preset templates")}</div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 14 }}>
            {systemTemplates.map(renderCard)}
          </div>
        )}

        <h2 style={{ fontSize: 16, fontWeight: 800, margin: "22px 0 10px" }}>{L("قوالبي الشخصية", "My personal templates")}</h2>
        {templates === null ? null : personalTemplates.length === 0 ? (
          <div className="card" style={{ textAlign: "center", color: "#5B7280" }}>
            {L("لا قوالب شخصية بعد — أنشئ أول قالب بالمنشئ العكسي", "No personal templates yet — create your first with the reverse builder")}
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 14 }}>
            {personalTemplates.map(renderCard)}
          </div>
        )}

        {structureTpl !== null ? (
          <Modal title={`${L("معاينة البنية", "Structure preview")} — ${structureTpl.name}`} spec="W-203" onClose={() => setStructureTpl(null)} wide>
            {structureTpl.structure.sections.map((section) => (
              <div key={section.section_key} style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "10px 0", borderBottom: "1px solid #EAF6F7" }}>
                <SectionKeyBox sectionKey={section.section_key} />
                <div>
                  <strong style={{ fontSize: 14 }}>{section.title}</strong>
                  <p style={{ fontSize: 12.5, color: "#5B7280", margin: "2px 0 0" }}>{section.instructions}</p>
                </div>
              </div>
            ))}
          </Modal>
        ) : null}
      </>
    );
  }

  /* ===== W-204 — المنشئ العكسي ===== */
  if (view === "builder") {
    return (
      <>
        <SpecBar ids="W-203 · W-204 · W-205" desc={L("الصفحة 13 — القائمة + المنشئ العكسي (إدخال ← معاينة/حفظ)", "Page 13 — list + reverse builder (input → preview/save)")} />
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 6 }}>
          <button className="btn-secondary h40" onClick={() => setView("list")}>{L("→ رجوع للقائمة", "← Back to list")}</button>
          <h1 style={{ fontSize: 18, fontWeight: 800, margin: 0, flex: 1, display: "inline-flex", alignItems: "center", gap: 8 }}>
            {L("منشئ القالب العكسي", "Reverse template builder")} <SpecBadge id="W-204" />
          </h1>
        </div>
        <p className="page-desc">
          {L("اكتب النص الذي تريده وطريقة تلخيصه، فيولّد الذكاء الاصطناعي بنية قالب قابلة للحفظ وإعادة الاستخدام (FR-502).",
             "Write the text you want and how it should be summarized — the AI generates a template structure you can save and reuse (FR-502).")}
        </p>

        <div className="card pad24">
          <label className="field-label">{L("نص المثال — كما تحب أن تبدو ملاحظتك", "Sample text — how you want your note to look")}</label>
          <textarea
            className="field clinical"
            dir="ltr"
            rows={7}
            placeholder="Paste an example of your ideal note structure…"
            value={sampleText}
            onChange={(event) => setSampleText(event.target.value)}
          />
          <label className="field-label">{L("طريقة التلخيص المرغوبة", "Preferred summarization style")}</label>
          <textarea
            className="field"
            rows={3}
            placeholder={L("مثال: اجعل التقييم قائمة مرقمة، والخطة نقاطاً قصيرة…", "Example: make the assessment a numbered list and the plan short bullet points…")}
            value={styleText}
            onChange={(event) => setStyleText(event.target.value)}
          />
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginTop: 16 }}>
            <button className="btn" onClick={() => void generate()} disabled={building}>
              {building ? <><span className="spinner" /> {L("يولّد البنية…", "Generating structure…")}</> : L("ولّد القالب", "Generate template")}
            </button>
            <span style={{ fontSize: 12.5, color: "#5B7280" }}>
              {L("لا يُحفظ شيء تلقائياً — المعاينة أولاً ثم الحفظ بفعلك (FR-503)",
                 "Nothing is saved automatically — preview first, then save by your own action (FR-503)")}
            </span>
          </div>
        </div>
      </>
    );
  }

  /* ===== W-205 — المعاينة والحفظ ===== */
  return (
    <>
      <SpecBar ids="W-203 · W-204 · W-205" desc={L("الصفحة 13 — القائمة + المنشئ العكسي (إدخال ← معاينة/حفظ)", "Page 13 — list + reverse builder (input → preview/save)")} />
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 6 }}>
        <button className="btn-secondary h40" onClick={() => setView("builder")}>{L("→ رجوع للتعديل", "← Back to editing")}</button>
        <h1 style={{ fontSize: 18, fontWeight: 800, margin: 0, flex: 1, display: "inline-flex", alignItems: "center", gap: 8 }}>
          {L("معاينة القالب المولّد", "Generated template preview")} <SpecBadge id="W-205" />
        </h1>
      </div>
      <p className="page-desc">
        {L("استُنتجت البنية من مثالك وشُغّلت على نص تجريبي قياسي (FR-503). لن يُحفظ القالب إلا بفعلك.",
           "The structure was inferred from your sample and run on a standard test text (FR-503). The template is saved only by your own action.")}
      </p>

      {generated === null ? (
        <div className="card" style={{ textAlign: "center", color: "#5B7280" }}>
          {L("لا بنية مولّدة — عد للمنشئ وولّد القالب أولاً.", "No generated structure — go back to the builder and generate the template first.")}
        </div>
      ) : (
        <>
          {/* البنية المستنتجة structure_json */}
          <h2 style={{ fontSize: 15, fontWeight: 800, margin: "0 0 4px" }}>
            {L("البنية المستنتجة", "Inferred structure")} <bdi>structure_json</bdi>
          </h2>
          {generated.structure.sections.map((section) => (
            <div
              key={section.section_key}
              className="card"
              style={{ marginTop: 10, border: section.section_key === "E" ? "1.5px solid #C9A227" : undefined }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <SectionKeyBox sectionKey={section.section_key} />
                <strong style={{ fontSize: 14 }}>{section.title}</strong>
                {section.section_key === "E" ? <span className="badge" style={GOLD_BADGE}>{L("قسم مستنتج جديد", "New inferred section")}</span> : null}
              </div>
              <p style={{ fontSize: 13, color: "#5B7280", margin: "8px 0 0" }}>{section.instructions}</p>
            </div>
          ))}

          {/* تشغيل على نص تجريبي قياسي */}
          <div className="card" style={{ marginTop: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <strong style={{ flex: 1, fontSize: 14 }}>{L("تشغيل على نص تجريبي قياسي", "Run on a standard test text")}</strong>
              <button className="btn-secondary h40" onClick={() => void runPreview()} disabled={running}>
                {running ? <><span className="spinner dark" /> {L("يشغّل…", "Running…")}</> : L("تشغيل المعاينة", "Run preview")}
              </button>
            </div>
            {runSections === null ? (
              <p style={{ fontSize: 12.5, color: "#5B7280", margin: "10px 0 0" }}>
                {L("اضغط «تشغيل المعاينة» لعرض ناتج القالب على النص التجريبي القياسي.",
                   "Press “Run preview” to see the template output on the standard test text.")}
              </p>
            ) : (
              runSections.map((section) => (
                <div key={section.section_key} style={{ display: "flex", gap: 10, alignItems: "flex-start", marginTop: 12 }}>
                  <SectionKeyBox sectionKey={section.section_key} />
                  <div className="clinical" style={{ flex: 1 }}>{section.content}</div>
                </div>
              ))
            )}
          </div>

          {/* بطاقة الحفظ */}
          <div className="card pad24" style={{ marginTop: 14 }}>
            <label className="field-label">{L("اسم القالب", "Template name")}</label>
            <input className="field" value={tplName} onChange={(event) => setTplName(event.target.value)} />
            {saveError !== null ? (
              <p style={{ color: "#C0392B", fontSize: 12.5, fontWeight: 700, margin: "10px 0 0" }}>
                {saveError} <bdi>(MDF-4225)</bdi>
              </p>
            ) : null}
            <div className="modal-actions">
              <button className="btn-success" onClick={() => void save()} disabled={saving}>
                {saving ? <span className="spinner" /> : null} {L("حفظ القالب", "Save template")}
              </button>
              <button className="btn-neutral" onClick={() => setView("list")}>{L("إلغاء", "Cancel")}</button>
            </div>
          </div>
        </>
      )}
    </>
  );
}

export default function DoctorTemplatesPage() {
  const { L } = useLang();
  return (
    <Shell title={L("قوالب التلخيص", "Summary templates")}>
      <main className="page-wrap narrow">
        <TemplatesInner />
      </main>
    </Shell>
  );
}
