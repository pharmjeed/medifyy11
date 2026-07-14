"use client";

/** الصفحة 6 — الدكاترة W-103 + نموذج الإنشاء W-104 (FR-202/203/204): مقاعد، تعطيل/تفعيل، إعادة كلمة المرور. */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { Field, Modal, SpecBar, useErrorScreen, useToast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Clinic, Doctor, SubscriptionInfo } from "@/lib/types";

const COLS = "1.6fr 1fr 1fr 1.2fr 1fr .8fr 1.6fr";
const SPECIALTIES = ["باطنة", "أطفال", "جلدية", "طب أسرة"];

function DoctorsInner() {
  const toast = useToast();
  const showError = useErrorScreen();

  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [sub, setSub] = useState<SubscriptionInfo | null>(null);
  const [clinics, setClinics] = useState<Clinic[]>([]);
  const [loading, setLoading] = useState(true);

  // نافذة الإنشاء W-104
  const [modalOpen, setModalOpen] = useState(false);
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [specialty, setSpecialty] = useState("باطنة");
  const [clinicId, setClinicId] = useState("");
  const [seatError, setSeatError] = useState(false);
  const [busy, setBusy] = useState(false);

  // نافذة كلمة المرور المؤقتة (FR-204)
  const [tempPw, setTempPw] = useState<{ doctor: string; password: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const [docB, subB, clinB] = await Promise.all([
        api<Doctor[]>("/doctors?per_page=50"),
        api<SubscriptionInfo>("/subscription"),
        api<Clinic[]>("/clinics"),
      ]);
      setDoctors(docB.data);
      setSub(subB.data);
      setClinics(clinB.data.filter((clinic) => clinic.archived_at === null));
    } catch (err) {
      showError(err);
    } finally {
      setLoading(false);
    }
  }, [showError]);

  useEffect(() => { void load(); }, [load]);

  const openCreate = () => {
    setFullName("");
    setUsername("");
    setPassword("");
    setSpecialty("باطنة");
    setClinicId(clinics[0]?.id ?? "");
    setSeatError(false);
    setModalOpen(true);
  };

  const submit = async () => {
    if (fullName.trim().length < 2) {
      toast("أدخل اسم الدكتور");
      return;
    }
    if (username.trim().length < 3 || password.length < 8) {
      toast("أكمل الحقول — اسم المستخدم 3 أحرف فأكثر وكلمة المرور 8 فأكثر");
      return;
    }
    if (clinicId === "") {
      toast("أنشئ عيادة أولاً ثم أضف الدكتور");
      return;
    }
    setBusy(true);
    setSeatError(false);
    try {
      await api("/doctors", {
        method: "POST",
        body: {
          full_name: fullName.trim(),
          username: username.trim(),
          password,
          specialty,
          clinic_id: clinicId,
        },
      });
      toast("أُنشئ حساب الدكتور واستُهلك مقعد");
      setModalOpen(false);
      await load();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "MDF-4221") setSeatError(true);
        else toast(`${err.messageAr} (${err.code})`);
      } else {
        toast("تعذر الاتصال بالخادم");
      }
    } finally {
      setBusy(false);
    }
  };

  const toggleActive = async (doctor: Doctor) => {
    try {
      await api(`/doctors/${doctor.id}`, { method: "PATCH", body: { is_active: !doctor.is_active } });
      toast(doctor.is_active
        ? "عُطّل الحساب — تحرر المقعد فوراً (FR-203)"
        : "فُعّل الحساب — استُهلك مقعد");
      await load();
    } catch (err) {
      if (err instanceof ApiError) toast(`${err.messageAr} (${err.code})`);
      else toast("تعذر الاتصال بالخادم");
    }
  };

  const resetPassword = async (doctor: Doctor) => {
    try {
      const body = await api<{ temporary_password: string }>(`/doctors/${doctor.id}/reset-password`, { method: "POST" });
      setTempPw({ doctor: doctor.full_name, password: body.data.temporary_password });
      toast("أُعيد تعيين كلمة المرور — أُرسل إشعار dr.password_reset (FR-204)");
    } catch (err) {
      if (err instanceof ApiError) toast(`${err.messageAr} (${err.code})`);
      else toast("تعذر الاتصال بالخادم");
    }
  };

  return (
    <main className="page-wrap">
      <SpecBar ids="W-103 · W-104" desc="الصفحة 6 — قائمة الدكاترة وحالة المقاعد + نموذج الإنشاء/التعديل (FR-202/204)" />

      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
        <h1 className="page-title" style={{ margin: 0 }}>الدكاترة</h1>
        {sub !== null ? (
          <span className={sub.seats_available > 0 ? "badge success" : "badge warn"}>
            المقاعد: <span className="num">{sub.seats_used}/{sub.seats_total}</span> مستهلكة
            · متاح <span className="num">{sub.seats_available}</span>
          </span>
        ) : null}
        <span style={{ flex: 1 }} />
        <button className="btn" onClick={openCreate}>+ دكتور جديد</button>
      </div>

      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: COLS }}>
          <div>الدكتور</div><div>المستخدم</div><div>التخصص</div><div>العيادة</div>
          <div>حالة المقعد</div><div>الزيارات</div><div>إجراءات</div>
        </div>
        {loading ? (
          <div className="grid-empty">جارٍ التحميل…</div>
        ) : doctors.length === 0 ? (
          <div className="grid-empty">لا دكاترة بعد — أضف أول دكتور (يستهلك مقعداً)</div>
        ) : (
          doctors.map((doctor, index) => (
            <div key={doctor.id} className={index % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: COLS }}>
              <div style={{ fontWeight: 700, color: doctor.is_active ? undefined : "#5B7280" }}>{doctor.full_name}</div>
              <div><bdi style={{ fontSize: 12.5 }}>{doctor.username}</bdi></div>
              <div>{doctor.specialty ?? "—"}</div>
              <div>{doctor.clinic_name ?? "—"}</div>
              <div>
                {doctor.is_active
                  ? <span className="badge success">نشط · مستهلك</span>
                  : <span className="badge neutral">معطّل · محرر</span>}
              </div>
              <div><span className="num">{doctor.visits_count}</span></div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button className="btn-row neutral" onClick={() => void toggleActive(doctor)}>
                  {doctor.is_active ? "تعطيل" : "تفعيل"}
                </button>
                <button className="btn-row" onClick={() => void resetPassword(doctor)}>إعادة كلمة المرور</button>
              </div>
            </div>
          ))
        )}
      </div>

      <p style={{ fontSize: 12.5, color: "#5B7280", marginTop: 10 }}>
        التعطيل يحرر المقعد فوراً لدكتور آخر — المقعد مملوك للمنشأة لا للشخص (DOC-09 §٢).
      </p>

      {/* نافذة الإنشاء W-104 */}
      {modalOpen ? (
        <Modal title="دكتور جديد" spec="W-104" onClose={() => setModalOpen(false)}>
          <p style={{ fontSize: 12.5, color: "#5B7280", margin: "0 0 12px" }}>
            كل دكتور نشط يستهلك مقعداً — المتاح الآن: <span className="num">{sub?.seats_available ?? 0}</span>
          </p>

          {seatError ? (
            <div style={{ background: "#FDEEEE", border: "1.5px solid #C0392B", borderRadius: 10, padding: "10px 14px", marginBottom: 12 }}>
              <div style={{ color: "#C0392B", fontWeight: 700 }}>
                لا مقاعد متاحة (<bdi>MDF-4221</bdi>) — لا يمكن إنشاء الدكتور
              </div>
              <div style={{ marginTop: 8 }}>
                <Link href="/admin/subscription" className="btn-danger" style={{ textDecoration: "none", height: 40 }}>
                  توسعة المقاعد
                </Link>
              </div>
            </div>
          ) : null}

          <Field
            label="الاسم الكامل"
            placeholder="مثال: د. سارة العمري"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
          />
          <Field
            label="اسم المستخدم"
            ltr
            placeholder="dr.username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
          <Field
            label="كلمة مرور مؤقتة"
            ltr
            type="password"
            placeholder="••••••••"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <label className="field-label">التخصص</label>
          <select className="field" value={specialty} onChange={(event) => setSpecialty(event.target.value)}>
            {SPECIALTIES.map((option) => <option key={option} value={option}>{option}</option>)}
          </select>
          <label className="field-label">العيادة</label>
          <select className="field" value={clinicId} onChange={(event) => setClinicId(event.target.value)}>
            {clinics.length === 0 ? <option value="">لا عيادات — أنشئ عيادة أولاً</option> : null}
            {clinics.map((clinic) => <option key={clinic.id} value={clinic.id}>{clinic.name}</option>)}
          </select>

          <div className="modal-actions">
            <button className="btn" onClick={() => void submit()} disabled={busy}>
              {busy ? <span className="spinner" /> : null} إنشاء الحساب (يستهلك مقعداً)
            </button>
            <button className="btn-neutral" onClick={() => setModalOpen(false)}>إلغاء</button>
          </div>
        </Modal>
      ) : null}

      {/* نافذة كلمة المرور المؤقتة */}
      {tempPw !== null ? (
        <Modal title="كلمة المرور المؤقتة" spec="W-104" onClose={() => setTempPw(null)}>
          <p style={{ fontSize: 14, margin: "0 0 10px" }}>{tempPw.doctor}</p>
          <div className="sub-box" style={{ textAlign: "center", fontSize: 22, fontWeight: 700 }}>
            <bdi>{tempPw.password}</bdi>
          </div>
          <p style={{ fontSize: 12.5, color: "#B07D10", fontWeight: 700, margin: "10px 0 0" }}>
            تُعرض مرة واحدة فقط — انسخها وسلّمها للدكتور الآن، ولن تظهر مجدداً.
          </p>
          <div className="modal-actions">
            <button className="btn" onClick={() => setTempPw(null)}>إغلاق</button>
          </div>
        </Modal>
      ) : null}
    </main>
  );
}

export default function DoctorsPage() {
  return (
    <Shell title="الدكاترة">
      <DoctorsInner />
    </Shell>
  );
}
