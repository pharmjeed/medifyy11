"use client";

/** صفحة الأدمن — تخصيص البرومبتات (W-203+) */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { Shell } from "@/components/Shell";
import { Modal, SpecBadge, SpecBar, useErrorScreen, useToast } from "@/components/ui";

interface TemplatePrompt {
  template_id: string;
  template_name: string;
  prompt_source: "default" | "custom";
  prompt_template_type: string | null;
  has_custom_prompt: boolean;
  prompt_preview: string | null;
}

export default function AdminPromptsPage() {
  const toast = useToast();
  const showError = useErrorScreen();
  const { L, lang } = useLang();

  const [templates, setTemplates] = useState<TemplatePrompt[] | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState<TemplatePrompt | null>(null);
  const [showEditor, setShowEditor] = useState(false);
  const [customContent, setCustomContent] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const body = await api<TemplatePrompt[]>("/settings/templates/prompts");
      setTemplates(body.data);
    } catch (err) {
      showError(err);
    }
  }, [showError]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleEdit = (template: TemplatePrompt) => {
    setSelectedTemplate(template);
    setCustomContent("");
    setShowEditor(true);
  };

  const handleSavePrompt = async () => {
    if (!selectedTemplate) return;

    if (customContent.trim().length === 0) {
      toast(L("أدخل محتوى البرومبت", "Enter prompt content"));
      return;
    }

    setSaving(true);
    try {
      await api(`/settings/templates/${selectedTemplate.template_id}/prompt`, {
        method: "PATCH",
        body: {
          prompt_content: customContent,
          prompt_source: "custom",
        },
      });
      toast(L("حُفظ البرومبت بنجاح", "Prompt saved successfully"));
      setShowEditor(false);
      void load();
    } catch (err) {
      showError(err);
    } finally {
      setSaving(false);
    }
  };

  const handleResetToDefault = async (templateId: string) => {
    setSaving(true);
    try {
      await api(`/settings/templates/${templateId}/prompt`, {
        method: "PATCH",
        body: {
          prompt_content: null,
          prompt_source: "default",
        },
      });
      toast(L("تمّ العودة للبرومبت الافتراضي", "Reset to default prompt"));
      void load();
    } catch (err) {
      showError(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Shell title={L("تخصيص البرومبتات", "Customize Prompts")}>
      <main className="page-wrap narrow">
        <SpecBar ids="W-203+" desc={L("الأدمن: تخصيص برومبتات القوالب", "Admin: Customize template prompts")} />

        <div style={{ marginBottom: 20 }}>
          <h1 className="page-title" style={{ marginBottom: 2 }}>
            {L("تخصيص البرومبتات", "Customize Prompts")}
          </h1>
          <p className="page-desc" style={{ margin: 0 }}>
            {L("خصّص برومبتات التلخيص لكل قالب حسب احتياجات منشأتك", "Customize summary prompts for each template to match your facility's needs")}
          </p>
        </div>

        {templates === null ? (
          <div className="card" style={{ textAlign: "center", color: "#5c7096" }}>
            {L("جارٍ التحميل…", "Loading…")}
          </div>
        ) : templates.length === 0 ? (
          <div className="card" style={{ textAlign: "center", color: "#5c7096" }}>
            {L("لا قوالب متاحة", "No templates available")}
          </div>
        ) : (
          <div style={{ display: "grid", gap: 12 }}>
            {templates.map((template) => (
              <div
                key={template.template_id}
                className="card"
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 10,
                  border: template.has_custom_prompt ? "1.5px solid #00c2b8" : undefined,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                  <div style={{ flex: 1 }}>
                    <strong style={{ fontSize: 15 }}>{template.template_name}</strong>
                    {template.has_custom_prompt && (
                      <span
                        className="badge"
                        style={{
                          marginLeft: 8,
                          background: "#00c2b8",
                          color: "#fff",
                        }}
                      >
                        {L("مخصص", "Custom")}
                      </span>
                    )}
                    {!template.has_custom_prompt && (
                      <span className="badge neutral" style={{ marginLeft: 8 }}>
                        {L("افتراضي", "Default")}
                      </span>
                    )}
                  </div>
                  <button className="btn-secondary h40" onClick={() => handleEdit(template)}>
                    {L("تحرير", "Edit")}
                  </button>
                </div>

                {template.prompt_preview && (
                  <p style={{ fontSize: 12, color: "#5c7096", margin: 0, fontStyle: "italic" }}>
                    "{template.prompt_preview}"
                  </p>
                )}

                {template.has_custom_prompt && (
                  <button
                    className="btn-row neutral"
                    onClick={() => void handleResetToDefault(template.template_id)}
                  >
                    {L("العودة للافتراضي", "Reset to Default")}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {showEditor && selectedTemplate && (
          <Modal
            title={`${L("تخصيص البرومبت", "Customize Prompt")} — ${selectedTemplate.template_name}`}
            onClose={() => setShowEditor(false)}
            wide
          >
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div>
                <label className="field-label">{L("محتوى البرومبت المخصص", "Custom Prompt Content")}</label>
                <textarea
                  className="field clinical"
                  rows={12}
                  value={customContent}
                  onChange={(e) => setCustomContent(e.target.value)}
                  placeholder={L("أدخل محتوى البرومبت المخصص للمنشأة…", "Enter custom prompt content…")}
                />
                <p style={{ fontSize: 12, color: "#5c7096", margin: "8px 0 0" }}>
                  {L("البرومبت يخبر الذكاء الاصطناعي كيفية تلخيص الزيارة", "The prompt tells the AI how to summarize the visit")}
                </p>
              </div>

              <div className="modal-actions">
                <button className="btn-success" onClick={() => void handleSavePrompt()} disabled={saving}>
                  {saving ? <span className="spinner" /> : null}
                  {L("حفظ التخصيص", "Save Customization")}
                </button>
                <button className="btn-neutral" onClick={() => setShowEditor(false)}>
                  {L("إلغاء", "Cancel")}
                </button>
              </div>
            </div>
          </Modal>
        )}
      </main>
    </Shell>
  );
}
