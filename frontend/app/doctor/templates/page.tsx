"use client";

/** الصفحة 13 — القوالب: W-203 (القائمة) + W-204 (المنشئ العكسي) + W-205 (المعاينة والحفظ). */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
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
      toast("التعيين الافتراضي متاح لقوالبك الشخصية");
      return;
    }
    try {
      await api(`/templates/${tpl.id}/default`, { method: "PATCH" });
      toast("عُيّن قالباً افتراضياً (FR-505)");
      void load();
    } catch (err) {
      showError(err);
    }
  };

  const removeTpl = async (tpl: Template) => {
    try {
      await api(`/templates/${tpl.id}`, { method: "DELETE" });
      toast("حُذف القالب الشخصي (FR-504)");
      void load();
    } catch (err) {
      showError(err);
    }
  };

  const generate = async () => {
    if (sampleText.trim() === "" || styleText.trim() === "") {
      toast("أدخل نص المثال وطريقة التلخيص أولاً (FR-502)");
      return;
    }
    setBuilding(true);
    try {
      const body = await api<GeneratedTemplate>("/templates/reverse-build", {
        method: "POST",
        body: { sample_text: sampleText, summarization_style: styleText },
      });
      setGenerated(body.data);
      setTplName(body.data.name.trim() !== "" ? body.data.name : "قالب عكسي جديد");
      setRunSections(null);
      setSaveError(null);
      setView("preview");
    } catch (err) {
      if (err instanceof ApiError && err.code === "MDF-5034") {
        toast(`${err.messageAr} — أعد المحاولة (MDF-5034)`);
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
        setSaveError(`بنية ناقصة — حدد النقص: ${err.messageAr}`);
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
      toast("أدخل اسم القالب");
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
      toast("حُفظ القالب — origin: reverse_built، جاهز لأي زيارة قادمة (FR-504)");
      setView("list");
      setGenerated(null);
      setRunSections(null);
      setSampleText("");
      setStyleText("");
      void load();
    } catch (err) {
      if (err instanceof ApiError && err.code === "MDF-4225") {
        setSaveError(`بنية ناقصة — حدد النقص: ${err.messageAr}`);
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
          title="تعيين افتراضي (FR-505)"
          aria-label="تعيين افتراضي (FR-505)"
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
        <span className="badge neutral"><span className="num">{tpl.structure.sections.length}</span> أقسام</span>
        {tpl.origin === "reverse_built" ? <span className="badge" style={GOLD_BADGE}>بناء عكسي</span> : null}
        {tpl.is_default ? <span className="badge" style={GOLD_BADGE}>الافتراضي</span> : null}
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: "auto" }}>
        <button className="btn-row" onClick={() => setStructureTpl(tpl)}>معاينة البنية</button>
        {tpl.is_personal ? (
          <button className="btn-row neutral" onClick={() => void removeTpl(tpl)}>حذف</button>
        ) : null}
      </div>
    </div>
  );

  /* ===== W-203 — القائمة ===== */
  if (view === "list") {
    return (
      <>
        <SpecBar ids="W-203 · W-204 · W-205" desc="الصفحة 13 — القائمة + المنشئ العكسي (إدخال ← معاينة/حفظ)" />
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 18 }}>
          <div style={{ flex: 1, minWidth: 240 }}>
            <h1 className="page-title" style={{ marginBottom: 2 }}>قوالب التلخيص</h1>
            <p className="page-desc" style={{ margin: 0 }}>الاختيار إلزامي قبل بدء أي تسجيل (FR-501)</p>
          </div>
          <button className="btn" onClick={() => setView("builder")}>+ قالب جديد عكسي</button>
        </div>

        <h2 style={{ fontSize: 16, fontWeight: 800, margin: "0 0 10px" }}>قوالب المنشأة الجاهزة</h2>
        {templates === null ? (
          <div className="card" style={{ textAlign: "center", color: "#5B7280" }}>جارٍ التحميل…</div>
        ) : systemTemplates.length === 0 ? (
          <div className="card" style={{ textAlign: "center", color: "#5B7280" }}>لا قوالب جاهزة</div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 14 }}>
            {systemTemplates.map(renderCard)}
          </div>
        )}

        <h2 style={{ fontSize: 16, fontWeight: 800, margin: "22px 0 10px" }}>قوالبي الشخصية</h2>
        {templates === null ? null : personalTemplates.length === 0 ? (
          <div className="card" style={{ textAlign: "center", color: "#5B7280" }}>
            لا قوالب شخصية بعد — أنشئ أول قالب بالمنشئ العكسي
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 14 }}>
            {personalTemplates.map(renderCard)}
          </div>
        )}

        {structureTpl !== null ? (
          <Modal title={`معاينة البنية — ${structureTpl.name}`} spec="W-203" onClose={() => setStructureTpl(null)} wide>
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
        <SpecBar ids="W-203 · W-204 · W-205" desc="الصفحة 13 — القائمة + المنشئ العكسي (إدخال ← معاينة/حفظ)" />
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 6 }}>
          <button className="btn-secondary h40" onClick={() => setView("list")}>→ رجوع للقائمة</button>
          <h1 style={{ fontSize: 18, fontWeight: 800, margin: 0, flex: 1, display: "inline-flex", alignItems: "center", gap: 8 }}>
            منشئ القالب العكسي <SpecBadge id="W-204" />
          </h1>
        </div>
        <p className="page-desc">
          اكتب النص الذي تريده وطريقة تلخيصه، فيولّد الذكاء الاصطناعي بنية قالب قابلة للحفظ وإعادة الاستخدام (FR-502).
        </p>

        <div className="card pad24">
          <label className="field-label">نص المثال — كما تحب أن تبدو ملاحظتك</label>
          <textarea
            className="field clinical"
            dir="ltr"
            rows={7}
            placeholder="Paste an example of your ideal note structure…"
            value={sampleText}
            onChange={(event) => setSampleText(event.target.value)}
          />
          <label className="field-label">طريقة التلخيص المرغوبة</label>
          <textarea
            className="field"
            rows={3}
            placeholder="مثال: اجعل التقييم قائمة مرقمة، والخطة نقاطاً قصيرة…"
            value={styleText}
            onChange={(event) => setStyleText(event.target.value)}
          />
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginTop: 16 }}>
            <button className="btn" onClick={() => void generate()} disabled={building}>
              {building ? <><span className="spinner" /> يولّد البنية…</> : "ولّد القالب"}
            </button>
            <span style={{ fontSize: 12.5, color: "#5B7280" }}>
              لا يُحفظ شيء تلقائياً — المعاينة أولاً ثم الحفظ بفعلك (FR-503)
            </span>
          </div>
        </div>
      </>
    );
  }

  /* ===== W-205 — المعاينة والحفظ ===== */
  return (
    <>
      <SpecBar ids="W-203 · W-204 · W-205" desc="الصفحة 13 — القائمة + المنشئ العكسي (إدخال ← معاينة/حفظ)" />
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 6 }}>
        <button className="btn-secondary h40" onClick={() => setView("builder")}>→ رجوع للتعديل</button>
        <h1 style={{ fontSize: 18, fontWeight: 800, margin: 0, flex: 1, display: "inline-flex", alignItems: "center", gap: 8 }}>
          معاينة القالب المولّد <SpecBadge id="W-205" />
        </h1>
      </div>
      <p className="page-desc">
        استُنتجت البنية من مثالك وشُغّلت على نص تجريبي قياسي (FR-503). لن يُحفظ القالب إلا بفعلك.
      </p>

      {generated === null ? (
        <div className="card" style={{ textAlign: "center", color: "#5B7280" }}>
          لا بنية مولّدة — عد للمنشئ وولّد القالب أولاً.
        </div>
      ) : (
        <>
          {/* البنية المستنتجة structure_json */}
          <h2 style={{ fontSize: 15, fontWeight: 800, margin: "0 0 4px" }}>
            البنية المستنتجة <bdi>structure_json</bdi>
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
                {section.section_key === "E" ? <span className="badge" style={GOLD_BADGE}>قسم مستنتج جديد</span> : null}
              </div>
              <p style={{ fontSize: 13, color: "#5B7280", margin: "8px 0 0" }}>{section.instructions}</p>
            </div>
          ))}

          {/* تشغيل على نص تجريبي قياسي */}
          <div className="card" style={{ marginTop: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <strong style={{ flex: 1, fontSize: 14 }}>تشغيل على نص تجريبي قياسي</strong>
              <button className="btn-secondary h40" onClick={() => void runPreview()} disabled={running}>
                {running ? <><span className="spinner dark" /> يشغّل…</> : "تشغيل المعاينة"}
              </button>
            </div>
            {runSections === null ? (
              <p style={{ fontSize: 12.5, color: "#5B7280", margin: "10px 0 0" }}>
                اضغط «تشغيل المعاينة» لعرض ناتج القالب على النص التجريبي القياسي.
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
            <label className="field-label">اسم القالب</label>
            <input className="field" value={tplName} onChange={(event) => setTplName(event.target.value)} />
            {saveError !== null ? (
              <p style={{ color: "#C0392B", fontSize: 12.5, fontWeight: 700, margin: "10px 0 0" }}>
                {saveError} <bdi>(MDF-4225)</bdi>
              </p>
            ) : null}
            <div className="modal-actions">
              <button className="btn-success" onClick={() => void save()} disabled={saving}>
                {saving ? <span className="spinner" /> : null} حفظ القالب
              </button>
              <button className="btn-neutral" onClick={() => setView("list")}>إلغاء</button>
            </div>
          </div>
        </>
      )}
    </>
  );
}

export default function DoctorTemplatesPage() {
  return (
    <Shell title="قوالب التلخيص">
      <main className="page-wrap narrow">
        <TemplatesInner />
      </main>
    </Shell>
  );
}
