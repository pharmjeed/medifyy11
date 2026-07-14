"use client";

/** الصفحة 3 — الملف الشخصي W-005: عرض /me + تغيير كلمة المرور الذاتية (DOC-06 §٢). */

import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { Field, SpecBar, initials, useErrorScreen, useToast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Me } from "@/lib/types";

function ProfileInner() {
  const toast = useToast();
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
      setPwError("أكمل الحقول الثلاثة أولاً.");
      return;
    }
    if (next.length < 8) {
      setPwError("كلمة المرور الجديدة 8 أحرف فأكثر.");
      return;
    }
    if (next !== confirm) {
      setPwError("تأكيد كلمة المرور لا يطابق الجديدة.");
      return;
    }
    setSaving(true);
    try {
      await api("/me/password", { method: "PATCH", body: { current_password: current, new_password: next } });
      toast("حُدّثت كلمة المرور بنجاح");
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      if (err instanceof ApiError) {
        setPwError(err.code === "MDF-4011" ? `كلمة المرور الحالية غير صحيحة (${err.code})` : `${err.messageAr} (${err.code})`);
      } else {
        setPwError("تعذر الاتصال بالخادم");
      }
    } finally {
      setSaving(false);
    }
  };

  const roleLabel = me === null ? "" : me.role === "admin" ? "أدمن المنشأة" : "دكتور";

  return (
    <main className="page-wrap slim">
      <SpecBar ids="W-005" desc="الصفحة 3 — الملف الشخصي /me (DOC-06)" />

      {loading ? (
        <div className="card"><div className="grid-empty">جارٍ التحميل…</div></div>
      ) : me === null ? (
        <div className="card"><div className="grid-empty">تعذر تحميل الملف الشخصي — أعد المحاولة</div></div>
      ) : (
        <>
          {/* بطاقة البيانات */}
          <div className="card pad24">
            <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <span className="avatar" style={{ width: 52, height: 52, fontSize: 18 }}>{initials(me.full_name)}</span>
              <div>
                <div style={{ fontSize: 18, fontWeight: 700 }}>{me.full_name}</div>
                <div style={{ fontSize: 12.5, color: "#5B7280" }}>
                  {me.facility_name} · الجلسة <bdi>JWT</bdi> 30 دقيقة مع تجديد
                </div>
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10, marginTop: 16 }}>
              <div className="sub-box">
                <div className="stat-label">اسم المستخدم</div>
                <bdi style={{ color: "#0E7C86", fontWeight: 700 }}>{me.username}</bdi>
              </div>
              <div className="sub-box">
                <div className="stat-label">الدور</div>
                <div style={{ fontWeight: 700 }}>{roleLabel}</div>
              </div>
              <div className="sub-box">
                <div className="stat-label">التخصص</div>
                <div style={{ fontWeight: 700 }}>{me.specialty ?? "—"}</div>
              </div>
              <div className="sub-box">
                <div className="stat-label">العيادة</div>
                <div style={{ fontWeight: 700 }}>{me.clinic_name ?? "—"}</div>
              </div>
            </div>

            <div className="info-box" style={{ marginTop: 14, display: "flex", gap: 8, alignItems: "flex-start" }}>
              <span aria-hidden="true" style={{ color: "#2A6F97", fontWeight: 700, flexShrink: 0 }}>ℹ</span>
              <span>الاسم والتخصص والعيادة يديرها أدمن المنشأة — تعديلك الذاتي محصور بكلمة المرور (DOC-06 §٢).</span>
            </div>
          </div>

          {/* بطاقة تغيير كلمة المرور */}
          <div className="card pad24" style={{ marginTop: 16 }}>
            <h2 style={{ fontSize: 18, fontWeight: 700, color: "#0A5C64", margin: "0 0 12px" }}>تغيير كلمة المرور</h2>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
              <div>
                <Field label="الحالية" ltr type="password" placeholder="••••••••" value={current}
                  onChange={(event) => setCurrent(event.target.value)} />
              </div>
              <div>
                <Field label="الجديدة" ltr type="password" placeholder="••••••••" value={next}
                  onChange={(event) => setNext(event.target.value)} />
              </div>
              <div>
                <Field label="تأكيد الجديدة" ltr type="password" placeholder="••••••••" value={confirm}
                  onChange={(event) => setConfirm(event.target.value)} />
              </div>
            </div>
            {pwError !== null ? (
              <p style={{ color: "#C0392B", fontSize: 12.5, fontWeight: 700, margin: "10px 0 0" }}>{pwError}</p>
            ) : null}
            <div style={{ marginTop: 16 }}>
              <button className="btn" onClick={() => void savePassword()} disabled={saving}>
                {saving ? <span className="spinner" /> : null} حفظ كلمة المرور
              </button>
            </div>
          </div>
        </>
      )}
    </main>
  );
}

export default function ProfilePage() {
  return (
    <Shell title="الملف الشخصي">
      <ProfileInner />
    </Shell>
  );
}
