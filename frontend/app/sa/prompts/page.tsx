"use client";

/** صفحة السوبر أدمن — إدارة البرومبتات الافتراضية (W-SA-10) */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { Shell } from "@/components/Shell";
import { Modal, SpecBadge, SpecBar, useErrorScreen, useToast } from "@/components/ui";

interface PromptVersion {
  version: string;
  is_active: boolean;
  created_at: string;
  updated_by: string | null;
}

interface PromptsByType {
  [templateType: string]: PromptVersion[];
}

const TEMPLATE_TYPES = {
  first_visit: "أول زيارة — First Visit",
  follow_up: "متابعة — Follow-up",
  consultation: "استشارة — Consultation",
};

export default function SuperAdminPromptsPage() {
  const toast = useToast();
  const showError = useErrorScreen();
  const { L, lang } = useLang();

  const [prompts, setPrompts] = useState<PromptsByType | null>(null);
  const [selectedType, setSelectedType] = useState<string | null>(null);
  const [showEditor, setShowEditor] = useState(false);
  const [newVersion, setNewVersion] = useState("1.1");
  const [newContent, setNewContent] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const body = await api<PromptsByType>("/sa/prompts");
      setPrompts(body.data);
    } catch (err) {
      showError(err);
    }
  }, [showError]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSavePrompt = async (templateType: string) => {
    if (!newContent.trim()) {
      toast(L("أدخل محتوى البرومبت", "Enter prompt content"));
      return;
    }
    setSaving(true);
    try {
      await api(`/sa/prompts/${templateType}`, {
        method: "POST",
        body: {
          prompt_content: newContent,
          version: newVersion,
        },
      });
      toast(L("حُفظ البرومبت بنجاح", "Prompt saved successfully"));
      setNewContent("");
      setNewVersion("1.1");
      setShowEditor(false);
      void load();
    } catch (err) {
      showError(err);
    } finally {
      setSaving(false);
    }
  };

  const handleActivate = async (templateType: string, version: string) => {
    try {
      await api(`/sa/prompts/${templateType}/activate?version=${version}`, {
        method: "PATCH",
      });
      toast(L("فُعِّل الإصدار بنجاح", "Version activated successfully"));
      void load();
    } catch (err) {
      showError(err);
    }
  };

  return (
    <Shell title={L("البرومبتات الافتراضية", "Default Prompts")}>
      <main className="page-wrap narrow">
        <SpecBar ids="W-SA-10" desc={L("السوبر أدمن: إدارة البرومبتات الافتراضية", "SuperAdmin: Manage default prompts")} />

        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
          <h1 className="page-title" style={{ marginBottom: 0 }}>
            {L("البرومبتات الافتراضية", "Default Prompts")}
          </h1>
        </div>

        {prompts === null ? (
          <div className="card" style={{ textAlign: "center", color: "#5c7096" }}>
            {L("جارٍ التحميل…", "Loading…")}
          </div>
        ) : (
          <div style={{ display: "grid", gap: 16 }}>
            {Object.entries(TEMPLATE_TYPES).map(([key, label]) => (
              <div key={key} className="card" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <strong style={{ fontSize: 16 }}>{label}</strong>
                  <button
                    className="btn-secondary h40"
                    onClick={() => {
                      setSelectedType(key);
                      setShowEditor(true);
                    }}
                  >
                    {L("إصدار جديد", "New Version")}
                  </button>
                </div>

                {prompts[key] ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {prompts[key].map((version) => (
                      <div
                        key={version.version}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          padding: 10,
                          background: "#f7f9fb",
                          borderRadius: 8,
                          border: version.is_active ? "1.5px solid #00c2b8" : "1px solid #d6f5f2",
                        }}
                      >
                        <div>
                          <strong>{version.version}</strong>
                          {version.is_active && (
                            <span className="badge" style={{ marginLeft: 8, background: "#00c2b8", color: "#fff" }}>
                              {L("نشط", "Active")}
                            </span>
                          )}
                        </div>
                        {!version.is_active && (
                          <button
                            className="btn-secondary h40"
                            onClick={() => void handleActivate(key, version.version)}
                          >
                            {L("تفعيل", "Activate")}
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p style={{ color: "#5c7096", fontSize: 13 }}>
                    {L("لا إصدارات متاحة", "No versions available")}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}

        {showEditor && selectedType && (
          <Modal
            title={`${L("إصدار جديد من", "New version of")} ${TEMPLATE_TYPES[selectedType as keyof typeof TEMPLATE_TYPES]}`}
            onClose={() => setShowEditor(false)}
            wide
          >
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div>
                <label className="field-label">{L("رقم الإصدار", "Version Number")}</label>
                <input
                  className="field"
                  value={newVersion}
                  onChange={(e) => setNewVersion(e.target.value)}
                  placeholder="1.1"
                />
              </div>

              <div>
                <label className="field-label">{L("محتوى البرومبت", "Prompt Content")}</label>
                <textarea
                  className="field clinical"
                  rows={12}
                  value={newContent}
                  onChange={(e) => setNewContent(e.target.value)}
                  placeholder={L("أدخل محتوى البرومبت الجديد…", "Enter prompt content…")}
                />
              </div>

              <div className="modal-actions">
                <button className="btn-success" onClick={() => void handleSavePrompt(selectedType)} disabled={saving}>
                  {saving ? <span className="spinner" /> : null}
                  {L("حفظ", "Save")}
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
