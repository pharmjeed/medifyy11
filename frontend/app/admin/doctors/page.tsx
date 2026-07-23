"use client";

/** الصفحة 6 — الدكاترة W-103 + نموذج الإنشاء W-104 (FR-202/203/204): مقاعد، تعطيل/تفعيل، إعادة كلمة المرور — ثنائية اللغة (D-30). */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { Field, Modal, SpecBar, useErrorScreen, useToast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import type { Clinic, Doctor, SubscriptionInfo } from "@/lib/types";

const COLS = "1.6fr 1fr 1fr 1.2fr 1fr .8fr 1.6fr";
const SPECIALTIES: { ar: string; en: string }[] = [
  { ar: "باطنة", en: "Internal medicine" },
  { ar: "أطفال", en: "Pediatrics" },
  { ar: "جلدية", en: "Dermatology" },
  { ar: "طب أسرة", en: "Family medicine" },
];

function DoctorsInner() {
  const toast = useToast();
  const showError = useErrorScreen();
  const { L, lang } = useLang();

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
      toast(L("أدخل اسم الدكتور", "Enter the doctor's name"));
      return;
    }
    if (username.trim().length < 3 || password.length < 8) {
      toast(L("أكمل الحقول — اسم المستخدم 3 أحرف فأكثر وكلمة المرور 8 فأكثر",
              "Complete the fields — username at least 3 characters and password at least 8"));
      return;
    }
    if (clinicId === "") {
      toast(L("أنشئ عيادة أولاً ثم أضف الدكتور", "Create a clinic first, then add the doctor"));
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
      toast(L("أُنشئ حساب الدكتور واستُهلك مقعد", "Doctor account created — one seat consumed"));
      setModalOpen(false);
      await load();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "MDF-4221") setSeatError(true);
        else toast(`${err.text(lang)} (${err.code})`);
      } else {
        toast(L("تعذر الاتصال بالخادم", "Could not reach the server"));
      }
    } finally {
      setBusy(false);
    }
  };

  const toggleActive = async (doctor: Doctor) => {
    try {
      await api(`/doctors/${doctor.id}`, { method: "PATCH", body: { is_active: !doctor.is_active } });
      toast(doctor.is_active
        ? L("عُطّل الحساب — تحرر المقعد فوراً (FR-203)", "Account disabled — seat freed immediately (FR-203)")
        : L("فُعّل الحساب — استُهلك مقعد", "Account enabled — one seat consumed"));
      await load();
    } catch (err) {
      if (err instanceof ApiError) toast(`${err.text(lang)} (${err.code})`);
      else toast(L("تعذر الاتصال بالخادم", "Could not reach the server"));
    }
  };

  const resetPassword = async (doctor: Doctor) => {
    try {
      const body = await api<{ temporary_password: string }>(`/doctors/${doctor.id}/reset-password`, { method: "POST" });
      setTempPw({ doctor: doctor.full_name, password: body.data.temporary_password });
      toast(L("أُعيد تعيين كلمة المرور — أُرسل إشعار dr.password_reset (FR-204)",
              "Password has been reset — dr.password_reset notification sent (FR-204)"));
    } catch (err) {
      if (err instanceof ApiError) toast(`${err.text(lang)} (${err.code})`);
      else toast(L("تعذر الاتصال بالخادم", "Could not reach the server"));
    }
  };

  // التخصص مخزّن بقيمته العربية — يُعرض بلغة الواجهة عند وجوده في الكتالوج
  const specialtyLabel = (value: string | null): string => {
    if (value === null || value === "") return "—";
    const option = SPECIALTIES.find((item) => item.ar === value);
    return option === undefined ? value : L(option.ar, option.en);
  };

  return (
    <main className="page-wrap">
      <SpecBar ids="W-103 · W-104" desc={L("الصفحة 6 — قائمة الدكاترة وحالة المقاعد + نموذج الإنشاء/التعديل (FR-202/204)",
                                           "Page 6 — doctor list and seat status + create/edit form (FR-202/204)")} />

      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
        <h1 className="page-title" style={{ margin: 0 }}>{L("الدكاترة", "Doctors")}</h1>
        {sub !== null ? (
          <span className={sub.seats_available > 0 ? "badge success" : "badge warn"}>
            {L("المقاعد:", "Seats:")} <span className="num">{sub.seats_used}/{sub.seats_total}</span> {L("مستهلكة", "used")}
            {" "}· {L("متاح", "available:")} <span className="num">{sub.seats_available}</span>
          </span>
        ) : null}
        <span style={{ flex: 1 }} />
        <button className="btn" onClick={openCreate}>{L("+ دكتور جديد", "+ New doctor")}</button>
      </div>

      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: COLS }}>
          <div>{L("الدكتور", "Doctor")}</div><div>{L("المستخدم", "Username")}</div><div>{L("التخصص", "Specialty")}</div><div>{L("العيادة", "Clinic")}</div>
          <div>{L("حالة المقعد", "Seat status")}</div><div>{L("الزيارات", "Visits")}</div><div>{L("إجراءات", "Actions")}</div>
        </div>
        {loading ? (
          <div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div>
        ) : doctors.length === 0 ? (
          <div className="grid-empty">{L("لا دكاترة بعد — أضف أول دكتور (يستهلك مقعداً)", "No doctors yet — add the first doctor (consumes a seat)")}</div>
        ) : (
          doctors.map((doctor, index) => (
            <div key={doctor.id} className={index % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: COLS }}>
              <div style={{ fontWeight: 700, color: doctor.is_active ? undefined : "#5c7096" }}>{doctor.full_name}</div>
              <div><bdi style={{ fontSize: 12.5 }}>{doctor.username}</bdi></div>
              <div>{specialtyLabel(doctor.specialty)}</div>
              <div>{doctor.clinic_name ?? "—"}</div>
              <div>
                {doctor.is_active
                  ? <span className="badge success">{L("نشط · مستهلك", "Active · seat used")}</span>
                  : <span className="badge neutral">{L("معطّل · محرر", "Disabled · seat freed")}</span>}
              </div>
              <div><span className="num">{doctor.visits_count}</span></div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button className="btn-row neutral" onClick={() => void toggleActive(doctor)}>
                  {doctor.is_active ? L("تعطيل", "Disable") : L("تفعيل", "Enable")}
                </button>
                <button className="btn-row" onClick={() => void resetPassword(doctor)}>{L("إعادة كلمة المرور", "Reset password")}</button>
              </div>
            </div>
          ))
        )}
      </div>

      <p style={{ fontSize: 12.5, color: "#5c7096", marginTop: 10 }}>
        {L("التعطيل يحرر المقعد فوراً لدكتور آخر — المقعد مملوك للمنشأة لا للشخص (DOC-09 §٢).",
           "Disabling frees the seat immediately for another doctor — the seat belongs to the facility, not the person (DOC-09 §2).")}
      </p>

      {/* نافذة الإنشاء W-104 */}
      {modalOpen ? (
        <Modal title={L("دكتور جديد", "New doctor")} spec="W-104" onClose={() => setModalOpen(false)}>
          <p style={{ fontSize: 12.5, color: "#5c7096", margin: "0 0 12px" }}>
            {L("كل دكتور نشط يستهلك مقعداً — المتاح الآن:", "Each active doctor consumes a seat — available now:")} <span className="num">{sub?.seats_available ?? 0}</span>
          </p>

          {seatError ? (
            <div style={{ background: "#fbeaea", border: "1.5px solid #d94b4b", borderRadius: 10, padding: "10px 14px", marginBottom: 12 }}>
              <div style={{ color: "#d94b4b", fontWeight: 700 }}>
                {L("لا مقاعد متاحة (", "No seats available (")}<bdi>MDF-4221</bdi>{L(") — لا يمكن إنشاء الدكتور", ") — the doctor cannot be created")}
              </div>
              <div style={{ marginTop: 8 }}>
                <Link href="/admin/subscription" className="btn-danger" style={{ textDecoration: "none", height: 40 }}>
                  {L("توسعة المقاعد", "Expand seats")}
                </Link>
              </div>
            </div>
          ) : null}

          <Field
            label={L("الاسم الكامل", "Full name")}
            placeholder={L("مثال: د. سارة العمري", "e.g. Dr. Sarah Al-Amri")}
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
          />
          <Field
            label={L("اسم المستخدم", "Username")}
            ltr
            placeholder="dr.username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
          <Field
            label={L("كلمة مرور مؤقتة", "Temporary password")}
            ltr
            type="password"
            placeholder="••••••••"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <label className="field-label">{L("التخصص", "Specialty")}</label>
          <select className="field" value={specialty} onChange={(event) => setSpecialty(event.target.value)}>
            {SPECIALTIES.map((option) => <option key={option.ar} value={option.ar}>{L(option.ar, option.en)}</option>)}
          </select>
          <label className="field-label">{L("العيادة", "Clinic")}</label>
          <select className="field" value={clinicId} onChange={(event) => setClinicId(event.target.value)}>
            {clinics.length === 0 ? <option value="">{L("لا عيادات — أنشئ عيادة أولاً", "No clinics — create a clinic first")}</option> : null}
            {clinics.map((clinic) => <option key={clinic.id} value={clinic.id}>{clinic.name}</option>)}
          </select>

          <div className="modal-actions">
            <button className="btn" onClick={() => void submit()} disabled={busy}>
              {busy ? <span className="spinner" /> : null} {L("إنشاء الحساب (يستهلك مقعداً)", "Create account (consumes a seat)")}
            </button>
            <button className="btn-neutral" onClick={() => setModalOpen(false)}>{L("إلغاء", "Cancel")}</button>
          </div>
        </Modal>
      ) : null}

      {/* نافذة كلمة المرور المؤقتة */}
      {tempPw !== null ? (
        <Modal title={L("كلمة المرور المؤقتة", "Temporary password")} spec="W-104" onClose={() => setTempPw(null)}>
          <p style={{ fontSize: 14, margin: "0 0 10px" }}>{tempPw.doctor}</p>
          <div className="sub-box" style={{ textAlign: "center", fontSize: 22, fontWeight: 700 }}>
            <bdi>{tempPw.password}</bdi>
          </div>
          <p style={{ fontSize: 12.5, color: "#9c6f00", fontWeight: 700, margin: "10px 0 0" }}>
            {L("تُعرض مرة واحدة فقط — انسخها وسلّمها للدكتور الآن، ولن تظهر مجدداً.",
               "Shown only once — copy it and hand it to the doctor now; it will not appear again.")}
          </p>
          <div className="modal-actions">
            <button className="btn" onClick={() => setTempPw(null)}>{L("إغلاق", "Close")}</button>
          </div>
        </Modal>
      ) : null}
    </main>
  );
}

export default function DoctorsPage() {
  const { L } = useLang();
  return (
    <Shell title={L("الدكاترة", "Doctors")}>
      <DoctorsInner />
    </Shell>
  );
}
