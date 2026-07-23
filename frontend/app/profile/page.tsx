"use client";

/** الصفحة 3 — الملف الشخصي W-005: عرض /me + تغيير كلمة المرور الذاتية (DOC-06 §٢). */

import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { Field, SpecBar, initials, useErrorScreen, useToast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import type { Me } from "@/lib/types";

function ProfileInner() {
  const toast = useToast();
  const { L, lang } = useLang();
  const showError = useErrorScreen();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pwError, setPwError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const body = await api<Me>("/me");
        setMe(body.data);
      } catch (err) {
        showError(err);
      } finally {
        setLoading(false);
      }
    })();
  }, [showError]);

  const savePassword = async () => {
    setPwError(null);
    if (current.length === 0 || next.length === 0 || confirm.length === 0) {
      setPwError(L("أكمل الحقول الثلاثة أولاً.", "Complete all three fields first."));
      return;
    }
    if (next.length < 8) {
      setPwError(L("كلمة المرور الجديدة 8 أحرف فأكثر.", "New password must be at least 8 characters."));
      return;
    }
    if (next !== confirm) {
      setPwError(L("تأكيد كلمة المرور لا يطابق الجديدة.", "Password confirmation does not match the new password."));
      return;
    }
    setSaving(true);
    try {
      await api("/me/password", { method: "PATCH", body: { current_password: current, new_password: next } });
      toast(L("حُدّثت كلمة المرور بنجاح", "Password updated successfully"));
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      if (err instanceof ApiError) {
        setPwError(err.code === "MDF-4011"
          ? `${L("كلمة المرور الحالية غير صحيحة", "Current password is incorrect")} (${err.code})`
          : `${err.text(lang)} (${err.code})`);
      } else {
        setPwError(L("تعذر الاتصال بالخادم", "Could not reach the server"));
      }
    } finally {
      setSaving(false);
    }
  };

  const roleLabel = me === null ? "" : me.role === "admin" ? L("أدمن المنشأة", "Facility admin") : L("دكتور", "Doctor");

  return (
    <main className="page-wrap slim">
      <SpecBar ids="W-005" desc={L("الصفحة 3 — الملف الشخصي /me (DOC-06)", "Page 3 — Profile /me (DOC-06)")} />

      {loading ? (
        <div className="card"><div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div></div>
      ) : me === null ? (
        <div className="card"><div className="grid-empty">{L("تعذر تحميل الملف الشخصي — أعد المحاولة", "Could not load profile — try again")}</div></div>
      ) : (
        <>
          {/* بطاقة البيانات */}
          <div className="card pad24">
            <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <span className="avatar" style={{ width: 52, height: 52, fontSize: 18 }}>{initials(me.full_name)}</span>
              <div>
                <div style={{ fontSize: 18, fontWeight: 700 }}>{me.full_name}</div>
                <div style={{ fontSize: 12.5, color: "#5c7096" }}>
                  {me.facility_name} · {L("الجلسة", "Session")} <bdi>JWT</bdi> {L("30 دقيقة مع تجديد", "30 minutes with renewal")}
                </div>
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10, marginTop: 16 }}>
              <div className="sub-box">
                <div className="stat-label">{L("اسم المستخدم", "Username")}</div>
                <bdi style={{ color: "#00736d", fontWeight: 700 }}>{me.username}</bdi>
              </div>
              <div className="sub-box">
                <div className="stat-label">{L("الدور", "Role")}</div>
                <div style={{ fontWeight: 700 }}>{roleLabel}</div>
              </div>
              <div className="sub-box">
                <div className="stat-label">{L("التخصص", "Specialty")}</div>
                <div style={{ fontWeight: 700 }}>{me.specialty ?? "—"}</div>
              </div>
              <div className="sub-box">
                <div className="stat-label">{L("العيادة", "Clinic")}</div>
                <div style={{ fontWeight: 700 }}>{me.clinic_name ?? "—"}</div>
              </div>
            </div>

            <div className="info-box" style={{ marginTop: 14, display: "flex", gap: 8, alignItems: "flex-start" }}>
              <span aria-hidden="true" style={{ color: "#3b82c4", fontWeight: 700, flexShrink: 0 }}>ℹ</span>
              <span>{L("الاسم والتخصص والعيادة يديرها أدمن المنشأة — تعديلك الذاتي محصور بكلمة المرور (DOC-06 §٢).",
                      "Name, specialty, and clinic are managed by the facility admin — self-service changes are limited to your password (DOC-06 §2).")}</span>
            </div>
          </div>

          {/* بطاقة تغيير كلمة المرور */}
          <div className="card pad24" style={{ marginTop: 16 }}>
            <h2 style={{ fontSize: 18, fontWeight: 700, color: "#005a55", margin: "0 0 12px" }}>{L("تغيير كلمة المرور", "Change password")}</h2>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
              <div>
                <Field label={L("الحالية", "Current password")} ltr type="password" placeholder="••••••••" value={current}
                  onChange={(event) => setCurrent(event.target.value)} />
              </div>
              <div>
                <Field label={L("الجديدة", "New password")} ltr type="password" placeholder="••••••••" value={next}
                  onChange={(event) => setNext(event.target.value)} />
              </div>
              <div>
                <Field label={L("تأكيد الجديدة", "Confirm new password")} ltr type="password" placeholder="••••••••" value={confirm}
                  onChange={(event) => setConfirm(event.target.value)} />
              </div>
            </div>
            {pwError !== null ? (
              <p style={{ color: "#d94b4b", fontSize: 12.5, fontWeight: 700, margin: "10px 0 0" }}>{pwError}</p>
            ) : null}
            <div style={{ marginTop: 16 }}>
              <button className="btn" onClick={() => void savePassword()} disabled={saving}>
                {saving ? <span className="spinner" /> : null} {L("حفظ كلمة المرور", "Save password")}
              </button>
            </div>
          </div>
        </>
      )}
    </main>
  );
}

export default function ProfilePage() {
  const { L } = useLang();
  return (
    <Shell title={L("الملف الشخصي", "Profile")}>
      <ProfileInner />
    </Shell>
  );
}
