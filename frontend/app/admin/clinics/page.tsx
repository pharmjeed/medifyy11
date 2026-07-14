"use client";

/** الصفحة 5 — إدارة العيادات W-102 (FR-201): جدول + نافذة إنشاء/تعديل + أرشفة ناعمة. */

import { useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { Field, Modal, SpecBar, useErrorScreen, useToast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Clinic } from "@/lib/types";

const COLS = "2fr 1fr 1fr 1.4fr";

function ClinicsInner() {
  const toast = useToast();
  const showError = useErrorScreen();

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
      toast("أدخل اسم العيادة");
      return;
    }
    setBusy(true);
    try {
      if (editingId !== null) {
        await api(`/clinics/${editingId}`, { method: "PATCH", body: { name: name.trim() } });
        toast("عُدّلت العيادة");
      } else {
        await api("/clinics", { method: "POST", body: { name: name.trim() } });
        toast("أُنشئت العيادة");
      }
      setModalOpen(false);
      await load();
    } catch (err) {
      if (err instanceof ApiError) toast(`${err.messageAr} (${err.code})`);
      else toast("تعذر الاتصال بالخادم");
    } finally {
      setBusy(false);
    }
  };

  const archive = async (clinic: Clinic) => {
    try {
      await api(`/clinics/${clinic.id}`, { method: "DELETE" });
      toast("أُرشفت العيادة — حذف ناعم (FR-201)");
      await load();
    } catch (err) {
      if (err instanceof ApiError) toast(`${err.messageAr} (${err.code})`);
      else toast("تعذر الاتصال بالخادم");
    }
  };

  return (
    <main className="page-wrap" style={{ maxWidth: 900 }}>
      <SpecBar ids="W-102" desc="الصفحة 5 — إدارة العيادات (FR-201) · الإنشاء/التعديل نافذة داخل القائمة" />

      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
        <h1 className="page-title" style={{ margin: 0, flex: 1 }}>عيادات المنشأة</h1>
        <button className="btn" onClick={openCreate}>+ عيادة جديدة</button>
      </div>

      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: COLS }}>
          <div>العيادة</div><div>الدكاترة</div><div>الحالة</div><div>إجراءات</div>
        </div>
        {loading ? (
          <div className="grid-empty">جارٍ التحميل…</div>
        ) : clinics.length === 0 ? (
          <div className="grid-empty">لا عيادات بعد — أنشئ أول عيادة</div>
        ) : (
          clinics.map((clinic, index) => {
            const archived = clinic.archived_at !== null;
            return (
              <div key={clinic.id} className={index % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: COLS }}>
                <div style={{ fontWeight: 700, color: archived ? "#5B7280" : undefined }}>{clinic.name}</div>
                <div><span className="num">{clinic.doctors_count}</span></div>
                <div>
                  {archived
                    ? <span className="badge neutral">مؤرشفة</span>
                    : <span className="badge success">نشطة</span>}
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button className="btn-row" onClick={() => openEdit(clinic)}>تعديل</button>
                  {!archived ? (
                    <button className="btn-row neutral" onClick={() => void archive(clinic)}>أرشفة</button>
                  ) : null}
                </div>
              </div>
            );
          })
        )}
      </div>

      <p style={{ fontSize: 12.5, color: "#5B7280", marginTop: 10 }}>
        الأرشفة حذف ناعم (<bdi>archived_at</bdi>) — لا حذف نهائياً للعيادات.
      </p>

      {modalOpen ? (
        <Modal
          title={editingId !== null ? "تعديل العيادة" : "عيادة جديدة"}
          spec="W-102"
          onClose={() => setModalOpen(false)}
        >
          <Field
            label="اسم العيادة"
            placeholder="مثال: عيادة الأنف والأذن"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <div className="modal-actions">
            <button className="btn" onClick={() => void save()} disabled={busy}>
              {busy ? <span className="spinner" /> : null} حفظ
            </button>
            <button className="btn-neutral" onClick={() => setModalOpen(false)}>إلغاء</button>
          </div>
        </Modal>
      ) : null}
    </main>
  );
}

export default function ClinicsPage() {
  return (
    <Shell title="العيادات">
      <ClinicsInner />
    </Shell>
  );
}
