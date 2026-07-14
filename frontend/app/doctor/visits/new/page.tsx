"use client";

/** الصفحة 14 — بدء زيارة + التسجيل:
 *  W-210 اختيار المريض (بحث + موجز الملف) · W-211 اختيار القالب · W-212 التسجيل الحي بتفريغ متدفق ·
 *  W-223 انقطاع الشبكة (حفظ محلي + resume_from) · W-213 حالة التوليد (P2→P3) · W-207 منشأة موقوفة.
 *  شريط التقدم السباعي الدائم (DOC-11 §٣). */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, getSessionUser, wsUrl } from "@/lib/api";
import type { CreatedVisit, Patient, PatientContext, Template } from "@/lib/types";
import { ProgressBar7 } from "@/components/ProgressBar7";
import { Shell } from "@/components/Shell";
import { Modal, SpecBadge, SpecBar, useErrorScreen, useToast } from "@/components/ui";

type Phase = "patient" | "template" | "recording" | "generating" | "blocked";

interface Segment { id: string; text: string; partial: boolean }

function medsText(context: PatientContext): string {
  return (context.medications ?? [])
    .map((med) => (typeof med === "string" ? med : `${med.name}${med.note !== undefined ? ` (${med.note})` : ""}`))
    .join(" · ") || "—";
}

export default function NewVisitPage() {
  const router = useRouter();
  const toast = useToast();
  const showError = useErrorScreen();

  const [phase, setPhase] = useState<Phase>("patient");
  const [patients, setPatients] = useState<Patient[]>([]);
  const [query, setQuery] = useState("");
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [visit, setVisit] = useState<CreatedVisit | null>(null);
  const [context, setContext] = useState<PatientContext | null>(null);

  // التسجيل الحي
  const [seconds, setSeconds] = useState(0);
  const [paused, setPaused] = useState(false);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [online, setOnline] = useState(true);
  const [offlineChunks, setOfflineChunks] = useState(0);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [genStep, setGenStep] = useState<0 | 1 | 2>(0); // 0 = P2 يجري · 1 = P3 يجري · 2 = اكتمل

  const ws = useRef<WebSocket | null>(null);
  const seq = useRef(0);
  const pending = useRef<{ seq: number; payload: string }[]>([]); // حفظ محلي عند الانقطاع (NFR-09)
  const timers = useRef<ReturnType<typeof setInterval>[]>([]);
  const pausedRef = useRef(false);
  const stopped = useRef(false);

  const suspended = getSessionUser()?.facility_status === "suspended";

  useEffect(() => {
    if (suspended) setPhase("blocked");
  }, [suspended]);

  useEffect(() => {
    void (async () => {
      try {
        const [patientsBody, templatesBody] = await Promise.all([
          api<Patient[]>(`/patients?per_page=50&query=${encodeURIComponent(query)}`),
          api<Template[]>("/templates"),
        ]);
        setPatients(patientsBody.data);
        setTemplates(templatesBody.data);
        const defaultTemplate = templatesBody.data.find((template) => template.is_default);
        setSelectedTemplate((current) => current ?? defaultTemplate ?? null);
      } catch (err) {
        showError(err);
      }
    })();
  }, [query, showError]);

  const clearTimers = useCallback(() => {
    for (const timer of timers.current) clearInterval(timer);
    timers.current = [];
  }, []);
  useEffect(() => () => { clearTimers(); ws.current?.close(); }, [clearTimers]);

  const connectWs = useCallback((visitId: string) => {
    const socket = new WebSocket(wsUrl(visitId));
    ws.current = socket;
    socket.onopen = () => {
      setOnline(true);
      // إعادة إرسال المخزن محلياً من آخر جزء مؤكد (NFR-09)
      for (const chunk of pending.current) {
        socket.send(JSON.stringify({ type: "audio_chunk", ...chunk, payload: chunk.payload }));
      }
      pending.current = [];
      setOfflineChunks(0);
    };
    socket.onmessage = (event) => {
      const message = JSON.parse(String(event.data)) as {
        type: string; text?: string; segment_id?: string; seq?: number; code?: string; state?: string;
      };
      if (message.type === "partial" && message.text !== undefined) {
        const text = message.text;
        setSegments((current) => {
          const rest = current.filter((segment) => !segment.partial);
          return [...rest, { id: "partial", text, partial: true }];
        });
      } else if (message.type === "final" && message.text !== undefined) {
        const text = message.text;
        const id = message.segment_id ?? `s-${Date.now()}`;
        setSegments((current) => [...current.filter((segment) => !segment.partial), { id, text, partial: false }]);
      } else if (message.type === "resume_from" && message.seq !== undefined) {
        seq.current = message.seq;
      } else if (message.type === "error") {
        toast(`انقطاع خط التفريغ (${message.code ?? "MDF-5031"}) — وضع الحفظ المحلي`);
        setOnline(false);
      }
    };
    socket.onclose = () => {
      if (stopped.current) return;
      setOnline(false); // W-223 — انقطاع الشبكة أثناء التسجيل
      setTimeout(() => {
        if (!stopped.current && phaseRef.current === "recording") connectWs(visitId);
      }, 2500);
    };
    socket.onerror = () => { /* onclose يتكفل */ };
  }, [toast]);

  const phaseRef = useRef<Phase>("patient");
  useEffect(() => { phaseRef.current = phase; }, [phase]);

  const startRecording = async () => {
    if (selectedPatient === null) { toast("اختر مريضاً أولاً (FR-601)"); return; }
    if (selectedTemplate === null) { toast("اختر قالباً — الاختيار إلزامي قبل التسجيل (FR-501)"); return; }
    try {
      const created = await api<CreatedVisit>("/visits", {
        method: "POST",
        body: { patient_id: selectedPatient.id, template_id: selectedTemplate.id },
      });
      setVisit(created.data);
      setContext(created.data.context_snapshot);
      await api(`/visits/${created.data.id}/recording/start`, { method: "POST" });
      setPhase("recording");
      stopped.current = false;
      connectWs(created.data.id);
      // ساعة التسجيل + مرسل الأجزاء (250ms لكل جزء — بروتوكول DOC-05 §٥)
      timers.current.push(setInterval(() => {
        if (!pausedRef.current) setSeconds((value) => value + 1);
      }, 1000));
      timers.current.push(setInterval(() => {
        if (pausedRef.current || stopped.current) return;
        const chunk = { seq: seq.current, payload: "AAAA" };
        seq.current += 1;
        const socket = ws.current;
        if (socket !== null && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "audio_chunk", ...chunk }));
        } else {
          pending.current.push(chunk); // حفظ محلي
          setOfflineChunks(pending.current.length);
        }
      }, 250));
    } catch (err) {
      if (err instanceof ApiError && err.code === "MDF-4013") { setPhase("blocked"); return; }
      showError(err);
    }
  };

  const togglePause = async () => {
    if (visit === null) return;
    const next = !paused;
    setPaused(next);
    pausedRef.current = next;
    ws.current?.send(JSON.stringify({ type: next ? "pause" : "resume" }));
    try {
      await api(`/visits/${visit.id}/recording/${next ? "pause" : "resume"}`, { method: "POST" });
    } catch { /* الحالة المحلية تكفي */ }
  };

  const finishRecording = async () => {
    if (visit === null) return;
    stopped.current = true;
    clearTimers();
    try { ws.current?.send(JSON.stringify({ type: "end" })); } catch { /* مغلق */ }
    ws.current?.close();
    setPhase("generating");
    setGenStep(0);
    const flip = setTimeout(() => setGenStep(1), 2400); // مؤشر P2 → P3 (W-213)
    try {
      await api(`/visits/${visit.id}/recording/stop`, {
        method: "POST",
        body: { duration_sec: seconds, pauses_count: 0, offline_chunks: offlineChunks },
      });
      clearTimeout(flip);
      setGenStep(2);
      setTimeout(() => router.push(`/doctor/visits/${visit.id}/review`), 700);
    } catch (err) {
      clearTimeout(flip);
      showError(err);
      setPhase("recording");
    }
  };

  const cancelVisit = async () => {
    if (visit === null) { router.push("/doctor"); return; }
    stopped.current = true;
    clearTimers();
    ws.current?.close();
    try {
      await api(`/visits/${visit.id}/cancel`, { method: "POST" });
      toast("أُلغيت الزيارة — حالة نهائية cancelled: لا اعتماد ولا رفع (FR-606)");
      router.push("/doctor/visits");
    } catch (err) {
      showError(err);
    }
  };

  const stage = phase === "recording" ? (segments.length > 0 ? 3 : 2) : phase === "generating" ? (genStep === 0 ? 4 : 5) : 1;
  const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
  const ss = String(seconds % 60).padStart(2, "0");

  return (
    <Shell title="زيارة جديدة">
      {phase !== "blocked" ? <ProgressBar7 current={stage} /> : null}
      <main className="page-wrap journey">
        <SpecBar ids="W-210 · W-211 · W-212 · W-213 · W-223" desc="الصفحة 14 — معالج (مريض ← قالب) ثم التسجيل بحالاته + الإلغاء" />

        {phase === "blocked" ? (
          <div className="card pad24" style={{ maxWidth: 620, margin: "40px auto", border: "2px solid #B07D10", textAlign: "center" }}>
            <SpecBadge id="W-207" />
            <div style={{ width: 56, height: 56, borderRadius: 999, background: "#FDF3E3", display: "inline-flex", alignItems: "center", justifyContent: "center", margin: "8px 0" }}>
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#B07D10" strokeWidth="2.2"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>
            </div>
            <div><bdi style={{ fontSize: 18, fontWeight: 700, color: "#B07D10" }}>MDF-4013</bdi></div>
            <h1 style={{ fontSize: 22, fontWeight: 800, margin: "6px 0" }}>إنشاء الزيارات موقوف مؤقتاً</h1>
            <p style={{ fontSize: 14, color: "#5B7280" }}>
              منشأتك عليها فاتورة متأخرة (DOC-09 §٢)، فتوقف إنشاء الزيارات الجديدة حتى السداد.<br />
              ما زال متاحاً لك: مراجعة واعتماد زياراتك القائمة، وسجل الزيارات للقراءة.
            </p>
            <p style={{ fontSize: 12.5, color: "#5B7280" }}>التعليق الكامل يوم 30 · البيانات محفوظة 90 يوماً ثم تُصدَّر وتُحذف وفق PDPL.</p>
            <Link href="/doctor" className="btn-secondary" style={{ textDecoration: "none", display: "inline-flex" }}>العودة للرئيسة</Link>
          </div>
        ) : null}

        {phase === "patient" ? (
          <div style={{ display: "grid", gridTemplateColumns: "1.2fr .9fr", gap: 16, alignItems: "start" }}>
            <section>
              <h1 className="page-title" style={{ display: "flex", gap: 8, alignItems: "center" }}>بدء زيارة — اختيار المريض <SpecBadge id="W-210" /></h1>
              <p className="page-desc">عند الاختيار تُجلب لقطة الملف التاريخي كسياق للتحليل (FR-601).</p>
              <div className="badge success" style={{ marginBottom: 10 }}>
                <span style={{ width: 8, height: 8, borderRadius: 999, background: "#2E9E5B" }} />
                قائمة المرضى مُزامنة من نظام المستشفى — لا إنشاء مرضى داخل Medify
              </div>
              <input className="field search" placeholder="ابحث بالاسم أو رقم الملف MRN…" value={query}
                onChange={(event) => setQuery(event.target.value)} style={{ marginBottom: 12 }} />
              <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 420, overflowY: "auto" }}>
                {patients.length === 0 ? (
                  <div className="grid-empty">
                    لا نتائج — البحث بالاسم أو MRN داخل منشأتك فقط.<br />
                    المريض غير موجود؟ سجّله في نظام المستشفى أولاً وسيظهر هنا مع المزامنة القادمة — لا إنشاء مرضى داخل Medify.
                  </div>
                ) : patients.map((patient) => {
                  const selected = selectedPatient?.id === patient.id;
                  return (
                    <button key={patient.id} className={selected ? "select-card selected" : "select-card"}
                      onClick={() => setSelectedPatient(patient)}
                      style={{ display: "flex", alignItems: "center", gap: 12 }}>
                      <span className="avatar">{patient.display_name.slice(0, 2)}</span>
                      <span style={{ flex: 1 }}>
                        <strong>{patient.display_name}</strong>
                        <span style={{ display: "block", fontSize: 12.5, color: "#5B7280" }}>
                          {patient.gender ?? "—"} · ملف <bdi>{patient.hospital_mrn}</bdi>
                        </span>
                      </span>
                      <span className="badge" style={{ background: selected ? "#E8F6EE" : "#F7FAFB", color: selected ? "#2E9E5B" : "#5B7280" }}>
                        {selected ? "محدد ✓" : "اختيار"}
                      </span>
                    </button>
                  );
                })}
              </div>
            </section>
            <aside style={{ position: "sticky", top: 120 }}>
              {selectedPatient !== null ? (
                <div className="card" style={{ border: "1.5px solid #0E7C86" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <strong style={{ fontSize: 16, flex: 1 }}>موجز ملف المريض</strong>
                    <span className="tech-badge">patient_context_snapshot</span>
                  </div>
                  <p style={{ margin: "10px 0 2px", fontWeight: 700 }}>{selectedPatient.display_name}</p>
                  <p style={{ margin: 0, fontSize: 12.5, color: "#5B7280" }}>
                    {selectedPatient.gender ?? "—"} · ملف <bdi>{selectedPatient.hospital_mrn}</bdi> · مزامنة {selectedPatient.synced_at.slice(0, 10)}
                  </p>
                  <p style={{ fontSize: 12.5, color: "#5B7280", margin: "10px 0 0" }}>
                    اللقطة بتاريخها تُحفظ لكل زيارة — قابلية تدقيق ما رآه الـ<bdi>AI</bdi> (DOC-04 §٤).
                    تُجلب اللقطة الكاملة (المزمنة/الأدوية/الحساسيات/النتائج) عند إنشاء الزيارة.
                  </p>
                  <button className="btn" style={{ width: "100%", marginTop: 14 }} onClick={() => setPhase("template")}>
                    التالي: اختيار القالب
                  </button>
                </div>
              ) : (
                <div style={{ border: "2px dashed #D7E3E8", borderRadius: 12, padding: 24, textAlign: "center", color: "#5B7280", fontSize: 14 }}>
                  اختر مريضاً لعرض موجز ملفه<br />
                  <span style={{ fontSize: 12.5 }}>الاسم وMRN للاختيار فقط — لقطة الملف ضمن زيارتك أنت (DOC-06 §٣)</span>
                </div>
              )}
            </aside>
          </div>
        ) : null}

        {phase === "template" ? (
          <section style={{ maxWidth: 620, margin: "0 auto" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <button className="btn-ghost" onClick={() => setPhase("patient")}>→ المريض</button>
              <h1 className="page-title" style={{ margin: 0, flex: 1, display: "flex", gap: 8, alignItems: "center" }}>
                اختيار قالب التلخيص <SpecBadge id="W-211" />
              </h1>
              <span style={{ fontSize: 12.5, color: "#5B7280" }}>المريض: {selectedPatient?.display_name}</span>
            </div>
            <p className="page-desc">الاختيار إلزامي قبل بدء التسجيل (FR-501) — قالبك الافتراضي محدد مسبقاً.</p>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {templates.filter((template) => template.archived_at === null).map((template) => {
                const selected = selectedTemplate?.id === template.id;
                return (
                  <button key={template.id} className={selected ? "select-card selected" : "select-card"} onClick={() => setSelectedTemplate(template)}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <strong style={{ flex: 1 }}>{template.name}</strong>
                      {template.is_default ? <span className="badge" style={{ background: "rgba(201,162,39,.15)", color: "#B07D10" }}>الافتراضي</span> : null}
                      {template.origin === "reverse_built" ? <span className="badge" style={{ background: "rgba(201,162,39,.15)", color: "#B07D10" }}>بناء عكسي</span> : null}
                      {template.is_personal ? <span className="badge info">شخصي</span> : <span className="badge neutral">جاهز</span>}
                    </div>
                    <div style={{ fontSize: 12.5, color: "#5B7280", marginTop: 4 }}>
                      {template.specialty ?? "—"} · {template.visit_type ?? "—"} · <span className="num">{template.structure.sections.length}</span> أقسام
                    </div>
                  </button>
                );
              })}
            </div>
            <button className="btn hero" style={{ width: "100%", marginTop: 16 }} onClick={() => void startRecording()}>
              <span style={{ width: 10, height: 10, borderRadius: 999, background: "#FDEEEE", animation: "mBlink 1.1s ease infinite" }} />
              بدء التسجيل
            </button>
          </section>
        ) : null}

        {phase === "recording" ? (
          <section style={{ maxWidth: 620, margin: "0 auto" }}>
            <div className="card pad24" style={{ border: online ? "1px solid #D7E3E8" : "2px solid #B07D10" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <SpecBadge id={online ? "W-212" : "W-223"} />
                <strong style={{ flex: 1 }}>{visit?.patient.display_name} · قالب: {visit?.template.name}</strong>
                <span className={online ? "badge success" : "badge danger"}>
                  <span style={{ width: 8, height: 8, borderRadius: 999, background: "currentColor" }} />
                  {online ? "متصل" : "غير متصل"}
                </span>
              </div>
              {!online ? (
                <div style={{ background: "#FDF3E3", border: "1px solid #B07D10", borderRadius: 10, padding: "10px 14px", margin: "12px 0 0", fontSize: 12.5, color: "#B07D10", fontWeight: 700 }}>
                  انقطاع الشبكة (<bdi>MDF-5031</bdi>) — وضع الحفظ المحلي: <span className="num">{offlineChunks}</span> جزءاً بانتظار الإرسال،
                  يُستأنف من آخر جزء مؤكد تلقائياً (NFR-09).
                </div>
              ) : null}
              <div style={{ display: "flex", alignItems: "center", gap: 16, margin: "16px 0" }}>
                <span style={{ width: 12, height: 12, borderRadius: 999, background: "#C0392B", animation: paused ? undefined : "mBlink 1.2s ease infinite" }} />
                <bdi style={{ fontSize: 28, fontWeight: 800, color: "#0A5C64" }}>{mm}:{ss}</bdi>
                <div className="wave" style={{ flex: 1, opacity: paused ? 0.3 : 1 }}>
                  {Array.from({ length: 16 }, (_, index) => (
                    <span key={index} style={{ animationDelay: `${(index % 8) * 0.09}s`, animationPlayState: paused ? "paused" : "running" }} />
                  ))}
                </div>
              </div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button className="btn-secondary" onClick={() => void togglePause()}>{paused ? "استئناف" : "إيقاف مؤقت"}</button>
                <button className="btn hero" style={{ flex: 1 }} onClick={() => void finishRecording()}>إنهاء التسجيل وتوليد الملخص</button>
                <button className="btn-danger-outline" onClick={() => setCancelOpen(true)}>إلغاء الزيارة</button>
              </div>
            </div>

            <div className="card" style={{ marginTop: 14 }}>
              <strong style={{ fontSize: 16 }}>التفريغ الفوري</strong>
              <span style={{ fontSize: 12.5, color: "#5B7280", marginInlineStart: 8 }}>partial ≤ 2s (NFR-01) · final بطوابع زمنية</span>
              <div style={{ display: "flex", flexDirection: "column-reverse", gap: 8, marginTop: 10, maxHeight: 320, overflowY: "auto" }}>
                {segments.length === 0 ? (
                  <p style={{ color: "#5B7280", fontSize: 14, textAlign: "center", margin: 12 }}>تحدّث الآن — يظهر التفريغ هنا فورياً…</p>
                ) : segments.map((segment) => (
                  <div key={segment.id} style={{ opacity: segment.partial ? 0.55 : 1, fontSize: 14, lineHeight: 1.9 }}>
                    <span className="badge" style={{ background: "#EAF6F7", color: "#0A5C64", marginInlineEnd: 8 }}>كلام</span>
                    {segment.text}
                    {segment.partial ? <span style={{ display: "inline-block", width: 2, height: 14, background: "#0E7C86", marginInlineStart: 4, animation: "mBlink .9s ease infinite" }} /> : null}
                  </div>
                ))}
              </div>
            </div>
          </section>
        ) : null}

        {phase === "generating" ? (
          <section style={{ maxWidth: 620, margin: "40px auto" }}>
            <div className="card pad24" style={{ textAlign: "center" }}>
              <SpecBadge id="W-213" />
              <h1 style={{ fontSize: 22, fontWeight: 800, margin: "10px 0 20px" }}>جارٍ توليد الملخص والإرشاد</h1>
              {[
                { label: "تلخيص SOAP وفق القالب", sub: "خط المعالجة P2", state: genStep >= 1 ? "done" : "run" },
                { label: "التحليل الذكي المدمج — سريري + ترميزي", sub: "خط المعالجة P3 على ملف المريض + كلام الزيارة", state: genStep === 2 ? "done" : genStep === 1 ? "run" : "wait" },
              ].map((step) => (
                <div key={step.label} style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 8px", borderTop: "1px solid #EAF6F7", textAlign: "start" }}>
                  {step.state === "done" ? (
                    <span style={{ width: 26, height: 26, borderRadius: 999, background: "#2E9E5B", color: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", fontWeight: 800 }}>✓</span>
                  ) : step.state === "run" ? (
                    <span className="spinner dark" style={{ width: 22, height: 22 }} />
                  ) : (
                    <span style={{ width: 26, height: 26, borderRadius: 999, border: "2px solid #D7E3E8" }} />
                  )}
                  <span style={{ flex: 1 }}>
                    <strong>{step.label}</strong>
                    <span style={{ display: "block", fontSize: 12.5, color: "#5B7280" }}>
                      {step.sub} — {step.state === "done" ? "اكتمل" : step.state === "run" ? "يجري الآن…" : "بانتظار الملخص"}
                    </span>
                  </span>
                </div>
              ))}
              <p style={{ fontSize: 12.5, color: "#5B7280", marginTop: 14 }}>≤ 30 ثانية لاستشارة 15 دقيقة (NFR-02) — فشل التحليل لا يحجب الملخص (W-224).</p>
            </div>
          </section>
        ) : null}

        {cancelOpen ? (
          <Modal title="إلغاء الزيارة" onClose={() => setCancelOpen(false)}>
            <div style={{ textAlign: "center" }}>
              <div style={{ width: 52, height: 52, borderRadius: 999, background: "#FDEEEE", display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#C0392B" strokeWidth="2"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
              </div>
              <p style={{ fontSize: 14, margin: "12px 0" }}>
                الإلغاء متاح أثناء التسجيل فقط — حالة نهائية <bdi>cancelled</bdi>: لا اعتماد ولا رفع، ويُحذف التسجيل (قرار مالك 2026-07-14).
              </p>
            </div>
            <div className="modal-actions">
              <button className="btn-danger" style={{ flex: 1 }} onClick={() => void cancelVisit()}>تأكيد الإلغاء</button>
              <button className="btn-neutral" style={{ flex: 1 }} onClick={() => setCancelOpen(false)}>متابعة التسجيل</button>
            </div>
          </Modal>
        ) : null}

        {phase === "patient" && context !== null ? null : null}
      </main>
    </Shell>
  );
}
