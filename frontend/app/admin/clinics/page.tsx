"use client";

/** الصفحة 5 — إدارة العيادات W-102 (FR-201): جدول + نافذة إنشاء/تعديل + أرشفة ناعمة. */

import { useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { Field, Modal, SpecBar, useErrorScreen, useToast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import type { Clinic } from "@/lib/types";

const COLS = "2fr 1fr 1fr 1.4fr";

function ClinicsInner() {
  const toast = useToast();
  const showError = useErrorScreen();
  const { L, lang } = useLang();

  const [clinics, setClinics] = useState<Clinic[]>([]);
  const [loading, setLoading] = useState(true);

  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const body = await api<Clinic[]>("/clinics?include_archived=true");
      setClinics(body.data);
    } catch (err) {
      showError(err);
    } finally {
      setLoading(false);
    }
  }, [showError]);

  useEffect(() => { void load(); }, [load]);

  const openCreate = () => {
    setEditingId(null);
    setName("");
    setModalOpen(true);
  };

  const openEdit = (clinic: Clinic) => {
    setEditingId(clinic.id);
    setName(clinic.name);
    setModalOpen(true);
  };

  const save = async () => {
    if (name.trim().length < 2) {
      toast(L("أدخل اسم العيادة", "Enter a clinic name"));
      return;
    }
    setBusy(true);
    try {
      if (editingId !== null) {
        await api(`/clinics/${editingId}`, { method: "PATCH", body: { name: name.trim() } });
        toast(L("عُدّلت العيادة", "Clinic updated"));
      } else {
        await api("/clinics", { method: "POST", body: { name: name.trim() } });
        toast(L("أُنشئت العيادة", "Clinic created"));
      }
      setModalOpen(false);
      await load();
    } catch (err) {
      if (err instanceof ApiError) toast(`${err.text(lang)} (${err.code})`);
      else toast(L("تعذر الاتصال بالخادم", "Could not reach the server"));
    } finally {
      setBusy(false);
    }
  };

  const archive = async (clinic: Clinic) => {
    try {
      await api(`/clinics/${clinic.id}`, { method: "DELETE" });
      toast(L("أُرشفت العيادة — حذف ناعم (FR-201)", "Clinic archived — soft delete (FR-201)"));
      await load();
    } catch (err) {
      if (err instanceof ApiError) toast(`${err.text(lang)} (${err.code})`);
      else toast(L("تعذر الاتصال بالخادم", "Could not reach the server"));
    }
  };

  return (
    <main className="page-wrap" style={{ maxWidth: 900 }}>
      <SpecBar ids="W-102" desc={L("الصفحة 5 — إدارة العيادات (FR-201) · الإنشاء/التعديل نافذة داخل القائمة",
        "Page 5 — Clinic management (FR-201) · Create/edit via in-list modal")} />

      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
        <h1 className="page-title" style={{ margin: 0, flex: 1 }}>{L("عيادات المنشأة", "Facility clinics")}</h1>
        <button className="btn" onClick={openCreate}>{L("+ عيادة جديدة", "+ New clinic")}</button>
      </div>

      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: COLS }}>
          <div>{L("العيادة", "Clinic")}</div><div>{L("الدكاترة", "Doctors")}</div><div>{L("الحالة", "Status")}</div><div>{L("إجراءات", "Actions")}</div>
        </div>
        {loading ? (
          <div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div>
        ) : clinics.length === 0 ? (
          <div className="grid-empty">{L("لا عيادات بعد — أنشئ أول عيادة", "No clinics yet — create your first clinic")}</div>
        ) : (
          clinics.map((clinic, index) => {
            const archived = clinic.archived_at !== null;
            return (
              <div key={clinic.id} className={index % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: COLS }}>
                <div style={{ fontWeight: 700, color: archived ? "#5B7280" : undefined }}>{clinic.name}</div>
                <div><span className="num">{clinic.doctors_count}</span></div>
                <div>
                  {archived
                    ? <span className="badge neutral">{L("مؤرشفة", "Archived")}</span>
                    : <span className="badge success">{L("نشطة", "Active")}</span>}
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button className="btn-row" onClick={() => openEdit(clinic)}>{L("تعديل", "Edit")}</button>
                  {!archived ? (
                    <button className="btn-row neutral" onClick={() => void archive(clinic)}>{L("أرشفة", "Archive")}</button>
                  ) : null}
                </div>
              </div>
            );
          })
        )}
      </div>

      <p style={{ fontSize: 12.5, color: "#5B7280", marginTop: 10 }}>
        {L("الأرشفة حذف ناعم (", "Archiving is a soft delete (")}<bdi>archived_at</bdi>{L(") — لا حذف نهائياً للعيادات.", ") — clinics are never permanently deleted.")}
      </p>

      {modalOpen ? (
        <Modal
          title={editingId !== null ? L("تعديل العيادة", "Edit clinic") : L("عيادة جديدة", "New clinic")}
          spec="W-102"
          onClose={() => setModalOpen(false)}
        >
          <Field
            label={L("اسم العيادة", "Clinic name")}
            placeholder={L("مثال: عيادة الأنف والأذن", "e.g. ENT clinic")}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <div className="modal-actions">
            <button className="btn" onClick={() => void save()} disabled={busy}>
              {busy ? <span className="spinner" /> : null} {L("حفظ", "Save")}
            </button>
            <button className="btn-neutral" onClick={() => setModalOpen(false)}>{L("إلغاء", "Cancel")}</button>
          </div>
        </Modal>
      ) : null}
    </main>
  );
}

export default function ClinicsPage() {
  const { L } = useLang();
  return (
    <Shell title={L("العيادات", "Clinics")}>
      <ClinicsInner />
    </Shell>
  );
}
