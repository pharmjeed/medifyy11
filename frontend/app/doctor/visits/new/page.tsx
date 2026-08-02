"use client";

/** الصفحة 14 — بدء زيارة + التسجيل:
 *  W-210 اختيار المريض (بحث + موجز الملف) · W-211 اختيار القالب · W-212 التسجيل (صوت فقط —
 *  لا تفريغ أثناء المحادثة، قرار مالك 2026-08-02) · W-223 انقطاع الشبكة (حفظ محلي + resume_from) ·
 *  W-213 حالة التوليد (P1 تفريغ كامل → P2 → P3) · W-207 منشأة موقوفة.
 *  شريط التقدم السباعي الدائم (DOC-11 §٣). */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, getSessionUser, wsUrl } from "@/lib/api";
import { startMicCapture } from "@/lib/audio";
import type { MicCapture } from "@/lib/audio";
import { cleanupOldChunks, deleteVisitChunks, getMaxStoredSeq, getPendingChunks, markSynced, storeChunk } from "@/lib/audio_storage";
import type { ConnectionState } from "@/lib/use_audio_ws";
import { UploadStatus } from "./components/UploadStatus";
import { useLang } from "@/lib/i18n";
import type { ConsentState, CreatedPatient, CreatedVisit, Patient, PatientContext, Template, VisitRow } from "@/lib/types";
import { ProgressBar7 } from "@/components/ProgressBar7";
import { Shell } from "@/components/Shell";
import { Field, Modal, SpecBadge, SpecBar, useErrorScreen, useToast } from "@/components/ui";

type Phase = "patient" | "template" | "consent" | "recording" | "generating" | "blocked";

const EMPTY_PATIENT_FORM = { hospital_mrn: "", display_name: "", dob: "", gender: "" };

/** مفتاح التسجيل النشط — ينجو من قتل التبويبة ليعرض «استئناف تسجيل منقطع» (المرحلة 2) */
const ACTIVE_RECORDING_KEY = "medify_active_recording";

interface ActiveRecordingMarker {
  visitId: string;
  startedAt: number;
  seconds: number;
  patientName: string;
}

function readActiveMarker(): ActiveRecordingMarker | null {
  try {
    const raw = localStorage.getItem(ACTIVE_RECORDING_KEY);
    if (raw === null) return null;
    const parsed = JSON.parse(raw) as ActiveRecordingMarker;
    return typeof parsed.visitId === "string" && parsed.visitId !== "" ? parsed : null;
  } catch { return null; }
}

/** بصمة sha256 لبايتات PCM (المخزنة base64) — يتحقق منها الخادم قبل كتابة المقطع */
async function sha256OfBase64(payload: string): Promise<string | undefined> {
  try {
    const raw = atob(payload);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
  } catch { return undefined; } // بيئة بلا WebCrypto — الخادم يحسبها بنفسه على أي حال
}

/** ينتظر إغلاق قناة التفريغ — الخادم يحفظ التفريغ قبل الإغلاق، فلا يبدأ التلخيص قبله */
function waitForSocketClose(socket: WebSocket | null, timeoutMs = 25000): Promise<void> {
  return new Promise((resolve) => {
    if (socket === null || socket.readyState === WebSocket.CLOSED) { resolve(); return; }
    const finish = (): void => { clearTimeout(timer); resolve(); };
    const timer = setTimeout(finish, timeoutMs);
    socket.addEventListener("close", finish, { once: true });
  });
}

function medsText(context: PatientContext): string {
  return (context.medications ?? [])
    .map((med) => (typeof med === "string" ? med : `${med.name}${med.note !== undefined ? ` (${med.note})` : ""}`))
    .join(" · ") || "—";
}

export default function NewVisitPage() {
  const router = useRouter();
  const toast = useToast();
  const showError = useErrorScreen();
  const { L } = useLang();

  const [phase, setPhase] = useState<Phase>("patient");
  const [patients, setPatients] = useState<Patient[]>([]);
  const [query, setQuery] = useState("");
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null);

  // إضافة مريض يدوياً — للمريض الذي لم يصل بعد من مزامنة نظام المستشفى (تعديل مالك 2026-07-26)
  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState(EMPTY_PATIENT_FORM);
  const [addBusy, setAddBusy] = useState(false);
  const [listVersion, setListVersion] = useState(0);

  const [templates, setTemplates] = useState<Template[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [visit, setVisit] = useState<CreatedVisit | null>(null);
  const [context, setContext] = useState<PatientContext | null>(null);

  // بوابة موافقة المريض (A1) — لا تسجيل قبل موافقة موثّقة
  const [consent, setConsent] = useState<ConsentState | null>(null);
  const [consentAck, setConsentAck] = useState(false);
  const [consentBusy, setConsentBusy] = useState(false);

  // التسجيل — صوت فقط (قرار مالك 2026-08-02): لا تفريغ قبل إنهاء المحادثة
  const [seconds, setSeconds] = useState(0);
  const [paused, setPaused] = useState(false);
  const [online, setOnline] = useState(true);
  const [offlineChunks, setOfflineChunks] = useState(0); // أجزاء بلا إقرار خادم (ack) بعد
  const [connState, setConnState] = useState<ConnectionState>("connecting");
  const [ackedChunks, setAckedChunks] = useState(0);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [genStep, setGenStep] = useState<0 | 1 | 2 | 3>(0); // 0 = P1 تفريغ كامل · 1 = P2 · 2 = P3 · 3 = اكتمل
  // مؤشر صوت صادق: الأعمدة من ذروات العينات الفعلية لا من أنيميشن — صمت رقمي متواصل = تحذير
  const [levels, setLevels] = useState<number[]>(Array.from({ length: 16 }, () => 0));
  const [micSilent, setMicSilent] = useState(false);
  const silentTicks = useRef(0);

  const ws = useRef<WebSocket | null>(null);
  const mic = useRef<MicCapture | null>(null); // الميكروفون الحي — PCM16 يُرسل كما هو للتفريغ
  // ترقيم واحد موحّد (المرحلة 2): seq المخزن الدائم هو نفسه chunk_index على الخادم —
  // معمَّر عبر الاتصالات وقتل التبويبة، فلا ازدواج ترقيم ولا خريطة سلكي/محلي
  const localSeq = useRef(0);
  const pending = useRef<{ seq: number; payload: string; sha256?: string }[]>([]);
  const sendChain = useRef<Promise<void>>(Promise.resolve()); // يسلسل الحفظ+البصمة حفاظاً على ترتيب seq
  const replaying = useRef(false);             // أثناء إعادة الإرسال بعد resume_from — الدفع الجديد مؤجل
  const unsynced = useRef(0);                  // أجزاء لم يقرّ الخادم كتابتها بعد
  const acked = useRef(0);
  const reconnectAttempts = useRef(0);         // تراجع أُسّي لإعادة الاتصال (سقف 30 ثانية)
  const timers = useRef<ReturnType<typeof setInterval>[]>([]);
  const pausedRef = useRef(false);
  const secondsRef = useRef(0);
  const stopped = useRef(false);
  const [resumeCandidate, setResumeCandidate] = useState<ActiveRecordingMarker | null>(null);

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
  }, [query, listVersion, showError]);

  const clearTimers = useCallback(() => {
    for (const timer of timers.current) clearInterval(timer);
    timers.current = [];
  }, []);
  useEffect(() => () => {
    clearTimers();
    mic.current?.stop();   // مغادرة الصفحة أثناء التسجيل تُطفئ الميكروفون فوراً
    mic.current = null;
    ws.current?.close();
  }, [clearTimers]);

  // يدفع قائمة الإرسال عبر القناة — seq المخزَّن يُرسل كما هو (ترقيم موحّد معمَّر)
  const flushPending = useCallback(() => {
    const socket = ws.current;
    if (replaying.current || socket === null || socket.readyState !== WebSocket.OPEN) return;
    let chunk = pending.current.shift();
    while (chunk !== undefined) {
      socket.send(JSON.stringify({ type: "audio_chunk", seq: chunk.seq, payload: chunk.payload, sha256: chunk.sha256 }));
      chunk = pending.current.shift();
    }
  }, []);

  const connectWs = useCallback((visitId: string) => {
    setConnState("connecting");
    const socket = new WebSocket(wsUrl(visitId));
    ws.current = socket;
    socket.onopen = () => {
      setOnline(true);
      setConnState("resuming");
      // لا نُرسل المخزَّن قبل أن يقول الخادم من أين يُكمل — موضع الاستئناف من سجل
      // audio_chunks المعمَّر (NFR-09 · المرحلة 2)، لا عدّاد جديد لكل اتصال.
      socket.send(JSON.stringify({ type: "resume_query" }));
    };
    socket.onmessage = (event) => {
      const message = JSON.parse(String(event.data)) as {
        type: string; seq?: number; code?: string; state?: string; reason?: string;
      };
      if (message.type === "ack" && message.seq !== undefined) {
        // الخادم ثبّت المقطع (ملف + صف سجل) — العدّاد الصادق من المخزن الدائم نفسه
        acked.current += 1;
        void markSynced(visitId, [message.seq])
          .then((remaining) => {
            unsynced.current = remaining;
            setOfflineChunks(remaining);
            setAckedChunks(acked.current);
          })
          .catch(() => undefined);
        setConnState("connected");
      } else if (message.type === "resume_from" && message.seq !== undefined) {
        // إعادة الإرسال من المخزن الدائم بترقيمه الأصلي — الخادم يعيد إقرار المكرر بلا كتابة
        replaying.current = true;
        const serverNext = message.seq;
        void (async () => {
          try {
            const stored = await getPendingChunks(visitId);
            pending.current = []; // المخزن الدائم يشمل ما في الذاكرة — قائمة إرسال واحدة
            for (const chunk of stored) {
              socket.send(JSON.stringify({ type: "audio_chunk", seq: chunk.seq, payload: chunk.payload, sha256: chunk.sha256 }));
            }
            const maxStored = stored.reduce((max, chunk) => Math.max(max, chunk.seq), -1);
            localSeq.current = Math.max(localSeq.current, serverNext, maxStored + 1);
          } catch { /* تعذرت القراءة — ما في الذاكرة يُرسل من الدورة التالية */ }
          replaying.current = false;
          reconnectAttempts.current = 0; // اتصال أثبت نفسه — يصفّر التراجع الأُسّي
          setConnState("connected");
        })();
      } else if (message.type === "chunk_error" && message.seq !== undefined) {
        // بصمة غير مطابقة (تلف في الطريق): المقطع باقٍ غير متزامن في المخزن — أعد المزامنة
        socket.send(JSON.stringify({ type: "resume_query" }));
      }
      // status: قناة الصوت حيّة — لا تفريغ يُبث أثناء التسجيل (قرار مالك 2026-08-02)
    };
    socket.onclose = () => {
      if (stopped.current) return;
      setOnline(false); // W-223 — انقطاع الشبكة أثناء التسجيل
      setConnState("disconnected");
      // تراجع أُسّي بسقف 30 ثانية + عشوائية خفيفة — لا قصف للخادم عند عطل ممتد
      const delay = Math.min(1000 * 1.5 ** reconnectAttempts.current, 30_000) + Math.random() * 300;
      reconnectAttempts.current += 1;
      setTimeout(() => {
        if (!stopped.current && phaseRef.current === "recording") connectWs(visitId);
      }, delay);
    };
    socket.onerror = () => { /* onclose يتكفل */ };
  }, []);

  const phaseRef = useRef<Phase>("patient");
  useEffect(() => { phaseRef.current = phase; }, [phase]);

  // تنظيف أجزاء صوت قديمة (أقدم من ٢٤ ساعة) من زيارات سابقة لم تكتمل
  useEffect(() => { void cleanupOldChunks().catch(() => undefined); }, []);

  // استئناف تسجيل منقطع (قتل تبويبة/انهيار متصفح): العلامة المحلية + تأكيد أن الزيارة
  // ما تزال recording على الخادم — الصوت السابق محفوظ هناك والاستئناف يُكمل بعده (المرحلة 2)
  useEffect(() => {
    const marker = readActiveMarker();
    if (marker === null) return;
    void (async () => {
      try {
        const body = await api<VisitRow[]>("/visits?state=recording&per_page=50");
        const row = body.data.find((candidate) => candidate.id === marker.visitId);
        if (row !== undefined) {
          setResumeCandidate({ ...marker, patientName: row.patient_name || marker.patientName });
        } else {
          localStorage.removeItem(ACTIVE_RECORDING_KEY); // انتهت خارج هذه التبويبة — علامة بائتة
        }
      } catch { /* الشبكة غير متاحة الآن — تبقى العلامة للمحاولة القادمة */ }
    })();
  }, []);

  const dismissResume = () => {
    localStorage.removeItem(ACTIVE_RECORDING_KEY);
    setResumeCandidate(null);
  };

  const resumeRecording = async () => {
    if (resumeCandidate === null) return;
    let capture: MicCapture;
    try {
      capture = await startMicCapture();
    } catch {
      toast(L("تعذّر تشغيل الميكروفون — اسمح بالوصول ثم أعد المحاولة",
              "Microphone unavailable — allow access, then try again"));
      return;
    }
    mic.current = capture;
    // زيارة مركّبة من علامة الاستئناف — recording لا يحتاج غير المعرّف واسم المريض للعرض
    setVisit({
      id: resumeCandidate.visitId,
      state: "recording",
      patient: { id: "", display_name: resumeCandidate.patientName, hospital_mrn: "" },
      template: { id: "", name: "" },
      context_snapshot: {},
    });
    setContext(null);
    const maxStored = await getMaxStoredSeq(resumeCandidate.visitId).catch(() => -1);
    localSeq.current = maxStored + 1; // resume_from من الخادم قد يرفعه أكثر
    secondsRef.current = resumeCandidate.seconds;
    setSeconds(resumeCandidate.seconds);
    setResumeCandidate(null);
    beginRecordingMechanics(resumeCandidate.visitId, resumeCandidate.patientName);
  };

  // إضافة مريض من داخل الزيارة — MRN مكرر يعيد الملف القائم بدل ازدواج
  const submitNewPatient = async () => {
    const mrn = addForm.hospital_mrn.trim();
    const name = addForm.display_name.trim();
    if (mrn === "" || name.length < 2) {
      toast(L("رقم الملف MRN والاسم إلزاميان", "MRN and full name are required"));
      return;
    }
    setAddBusy(true);
    try {
      const created = await api<CreatedPatient>("/patients", {
        method: "POST",
        body: {
          hospital_mrn: mrn,
          display_name: name,
          dob: addForm.dob.trim() === "" ? null : addForm.dob.trim(),
          gender: addForm.gender.trim() === "" ? null : addForm.gender.trim(),
        },
      });
      setSelectedPatient(created.data);
      setAddOpen(false);
      setAddForm(EMPTY_PATIENT_FORM);
      setQuery("");
      setListVersion((value) => value + 1);
      toast(created.data.already_exists
        ? L("رقم الملف مسجّل مسبقاً — اختير الملف القائم", "MRN already registered — the existing file was selected")
        : L("أُضيف المريض واختير لهذه الزيارة", "Patient added and selected for this visit"));
    } catch (err) {
      if (err instanceof ApiError && err.code === "MDF-4013") { setPhase("blocked"); return; }
      showError(err);
    } finally {
      setAddBusy(false);
    }
  };

  // الخطوة قبل الأخيرة: أنشئ الزيارة (draft) واعرض بوابة الموافقة قبل أي تسجيل
  const proceedToConsent = async () => {
    if (selectedPatient === null) { toast(L("اختر مريضاً أولاً (FR-601)", "Select a patient first (FR-601)")); return; }
    if (selectedTemplate === null) { toast(L("اختر قالباً — الاختيار إلزامي قبل التسجيل (FR-501)", "Select a template — selection is required before recording (FR-501)")); return; }
    try {
      const created = await api<CreatedVisit>("/visits", {
        method: "POST",
        body: { patient_id: selectedPatient.id, template_id: selectedTemplate.id },
      });
      setVisit(created.data);
      setContext(created.data.context_snapshot);
      const consentBody = await api<ConsentState>(`/visits/${created.data.id}/consent`);
      setConsent(consentBody.data);
      setConsentAck(false);
      setPhase("consent");
    } catch (err) {
      if (err instanceof ApiError && err.code === "MDF-4013") { setPhase("blocked"); return; }
      showError(err);
    }
  };

  // آليات التسجيل الحي — لا تُستدعى إلا بعد توثيق الموافقة (MDF-4230 خلاف ذلك)
  const beginRecordingMechanics = (visitId: string, patientName?: string) => {
    setPhase("recording");
    stopped.current = false;
    // علامة التسجيل النشط — تنجو من قتل التبويبة لعرض «استئناف» (تُمسح عند الإنهاء/الإلغاء)
    try {
      localStorage.setItem(ACTIVE_RECORDING_KEY, JSON.stringify({
        visitId,
        startedAt: Date.now(),
        seconds: secondsRef.current,
        patientName: patientName ?? selectedPatient?.display_name ?? "",
      } satisfies ActiveRecordingMarker));
    } catch { /* تخزين محلي معطّل — الاستئناف بعد قتل التبويبة غير متاح فقط */ }
    connectWs(visitId);
    // ساعة التسجيل + مرسل الأجزاء (250ms لكل جزء — بروتوكول DOC-05 §٥)
    timers.current.push(setInterval(() => {
      if (pausedRef.current) return;
      secondsRef.current += 1;
      setSeconds(secondsRef.current);
      if (secondsRef.current % 5 === 0) {
        // تحديث دوري لعداد الثواني في العلامة — استئناف ما بعد الانهيار يعرض مدة صادقة
        try {
          const marker = readActiveMarker();
          if (marker !== null && marker.visitId === visitId) {
            localStorage.setItem(ACTIVE_RECORDING_KEY,
              JSON.stringify({ ...marker, seconds: secondsRef.current }));
          }
        } catch { /* غير حرج */ }
      }
    }, 1000));
    timers.current.push(setInterval(() => {
      if (pausedRef.current || stopped.current) return;
      // مقياس المستوى + كاشف الصمت الرقمي: ذروة 0 متواصلة = الميكروفون لا يُوصِل إشارة (مكتوم/جهاز خاطئ)
      const peak = mic.current?.peak() ?? 0;
      setLevels((current) => [...current.slice(1), peak]);
      if (peak < 0.0015 || mic.current?.trackMuted() === true) {
        silentTicks.current += 1;
        if (silentTicks.current >= 20) setMicSilent(true); // ~5 ثوانٍ صمت مطلق
      } else {
        silentTicks.current = 0;
        setMicSilent(false);
      }
      const payload = mic.current?.drain() ?? "";
      if (payload === "") return; // لا صوت متجمّع في هذه الدورة
      const localId = localSeq.current;
      localSeq.current += 1;
      // سلسلة تسلسلية: بصمة sha256 ثم الحفظ الدائم (IndexedDB) ثم الدفع — الترتيب محفوظ
      // حتى مع تفاوت زمن حساب البصمات، والجزء ينجو من الانقطاع وتحديث الصفحة
      sendChain.current = sendChain.current.then(async () => {
        const digest = await sha256OfBase64(payload);
        try {
          await storeChunk({ visitId, seq: localId, payload, sha256: digest, timestamp: Date.now(), synced: false });
        } catch { /* المخزن الدائم متعذر — الإرسال الحي يستمر */ }
        unsynced.current += 1;
        pending.current.push({ seq: localId, payload, sha256: digest });
        flushPending();
        setOfflineChunks(unsynced.current);
        setAckedChunks(acked.current);
      });
    }, 250));
  };

  // توثيق الموافقة ثم بدء التسجيل — الحارس التقني: لا تسجيل قبلها
  const confirmConsentAndRecord = async () => {
    if (visit === null || !consentAck) return;
    setConsentBusy(true);
    // الميكروفون أولاً: الموافقة سجل إلحاقي لا يُوثَّق ما لم يكن التسجيل ممكناً فعلاً
    let capture: MicCapture;
    try {
      capture = await startMicCapture();
    } catch {
      setConsentBusy(false);
      toast(L("تعذّر تشغيل الميكروفون — اسمح بالوصول للميكروفون من المتصفح ثم أعد المحاولة",
              "Microphone unavailable — allow microphone access in the browser, then try again"));
      return;
    }
    mic.current = capture;
    try {
      await api(`/visits/${visit.id}/consent`, {
        method: "POST",
        body: { acknowledged: true, method: "verbal_ack" },
      });
      await api(`/visits/${visit.id}/recording/start`, { method: "POST" });
      beginRecordingMechanics(visit.id);
    } catch (err) {
      capture.stop();
      mic.current = null;
      if (err instanceof ApiError && err.code === "MDF-4013") { setPhase("blocked"); return; }
      showError(err);
    } finally {
      setConsentBusy(false);
    }
  };

  const togglePause = async () => {
    if (visit === null) return;
    const next = !paused;
    setPaused(next);
    pausedRef.current = next;
    mic.current?.setPaused(next); // الإيقاف المؤقت يوقف التقاط الصوت لا الميكروفون
    ws.current?.send(JSON.stringify({ type: next ? "pause" : "resume" }));
    try {
      await api(`/visits/${visit.id}/recording/${next ? "pause" : "resume"}`, { method: "POST" });
    } catch { /* الحالة المحلية تكفي */ }
  };

  const finishRecording = async () => {
    if (visit === null) return;
    stopped.current = true;
    clearTimers();
    // آخر ما التقطه الميكروفون يُحفظ ثم يُرسل قبل الإنهاء، ثم يُطفأ الجهاز
    const socket = ws.current;
    const tail = mic.current?.drain() ?? "";
    mic.current?.stop();
    mic.current = null;
    if (tail !== "") {
      const localId = localSeq.current;
      localSeq.current += 1;
      sendChain.current = sendChain.current.then(async () => {
        const digest = await sha256OfBase64(tail);
        try {
          await storeChunk({ visitId: visit.id, seq: localId, payload: tail, sha256: digest, timestamp: Date.now(), synced: false });
        } catch { /* المخزن الدائم متعذر */ }
        unsynced.current += 1;
        pending.current.push({ seq: localId, payload: tail, sha256: digest });
      });
    }
    // تفريغ سلسلة الإرسال كاملة (بصمات + حفظ دائم) قبل الذيل والإنهاء — الترتيب حاكم
    await sendChain.current.catch(() => undefined);
    if (socket !== null && socket.readyState === WebSocket.OPEN) {
      try {
        flushPending();
        socket.send(JSON.stringify({ type: "end" }));
      } catch { /* مغلق */ }
    }
    setPhase("generating");
    setGenStep(0);
    // مؤشرا تقدم تقريبيان (W-213): المعالجة كلها استدعاء واحد متزامن — تفريغ كامل ثم P2 ثم P3
    const flipToSummary = setTimeout(() => setGenStep(1), 5000);
    const flipToGuidance = setTimeout(() => setGenStep(2), 10_000);
    // الخادم يُغلق القناة بعد اكتمال ملف الصوت — الانتظار يضمن أن التفريغ يقرأ المحادثة كاملة
    await waitForSocketClose(socket);
    try {
      await api(`/visits/${visit.id}/recording/stop`, {
        method: "POST",
        body: { duration_sec: seconds, pauses_count: 0, offline_chunks: offlineChunks },
      });
      clearTimeout(flipToSummary);
      clearTimeout(flipToGuidance);
      setGenStep(3);
      try { localStorage.removeItem(ACTIVE_RECORDING_KEY); } catch { /* غير حرج */ }
      // اكتمل الرفع بلا بقايا؟ يُنظَّف المخزن الدائم — وإلا يبقى للتعافي وتزيله مهلة 24 ساعة
      if (unsynced.current === 0) void deleteVisitChunks(visit.id).catch(() => undefined);
      setTimeout(() => router.push(`/doctor/visits/${visit.id}/review`), 700);
    } catch (err) {
      clearTimeout(flipToSummary);
      clearTimeout(flipToGuidance);
      // MDF-4234: مقاطع ناقصة/غير مطابقة على الخادم — عودة للتسجيل بقناة حيّة تعيد المزامنة
      if (err instanceof ApiError && err.code === "MDF-4234") {
        toast(L("الملف الصوتي لم يكتمل على الخادم — أُعيد فتح القناة للمزامنة، أنهِ مجدداً بعد اكتمالها",
                "Audio not fully synced on the server — channel reopened to resync; finish again once synced"));
      } else {
        showError(err);
      }
      stopped.current = false;
      mic.current = await startMicCapture().catch(() => null);
      beginRecordingMechanics(visit.id, visit.patient.display_name);
    }
  };

  const cancelVisit = async () => {
    if (visit === null) { router.push("/doctor"); return; }
    stopped.current = true;
    clearTimers();
    mic.current?.stop();
    mic.current = null;
    ws.current?.close();
    try {
      await api(`/visits/${visit.id}/cancel`, { method: "POST" });
      void deleteVisitChunks(visit.id).catch(() => undefined); // زيارة ملغاة — لا حاجة لصوتها المخزّن
      try { localStorage.removeItem(ACTIVE_RECORDING_KEY); } catch { /* غير حرج */ }
      toast(L("أُلغيت الزيارة — حالة نهائية cancelled: لا اعتماد ولا رفع (FR-606)",
              "Visit cancelled — final state cancelled: no approval, no upload (FR-606)"));
      router.push("/doctor/visits");
    } catch (err) {
      showError(err);
    }
  };

  // المرحلة 3 (تفريغ) تعيش الآن داخل شاشة التوليد — لا تفريغ أثناء التسجيل
  const stage = phase === "recording" ? 2 : phase === "generating" ? (genStep === 0 ? 3 : genStep === 1 ? 4 : 5) : 1;
  const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
  const ss = String(seconds % 60).padStart(2, "0");

  return (
    <Shell title={L("زيارة جديدة", "New visit")}>
      {phase !== "blocked" ? <ProgressBar7 current={stage} /> : null}
      <main className="page-wrap journey">
        <SpecBar ids="W-210 · W-211 · W-212 · W-213 · W-223" desc={L("الصفحة 14 — معالج (مريض ← قالب) ثم التسجيل بحالاته + الإلغاء", "Page 14 — wizard (patient → template) then recording with its states + cancellation")} />

        {phase === "blocked" ? (
          <div className="card pad24" style={{ maxWidth: 620, margin: "40px auto", border: "2px solid #9c6f00", textAlign: "center" }}>
            <SpecBadge id="W-207" />
            <div style={{ width: 56, height: 56, borderRadius: 999, background: "#fdf4e0", display: "inline-flex", alignItems: "center", justifyContent: "center", margin: "8px 0" }}>
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#9c6f00" strokeWidth="2.2"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>
            </div>
            <div><bdi style={{ fontSize: 18, fontWeight: 700, color: "#9c6f00" }}>MDF-4013</bdi></div>
            <h1 style={{ fontSize: 22, fontWeight: 800, margin: "6px 0" }}>{L("إنشاء الزيارات موقوف مؤقتاً", "Visit creation is temporarily suspended")}</h1>
            <p style={{ fontSize: 14, color: "#5c7096" }}>
              {L("منشأتك عليها فاتورة متأخرة (DOC-09 §٢)، فتوقف إنشاء الزيارات الجديدة حتى السداد.",
                 "Your facility has an overdue invoice (DOC-09 §2), so creating new visits is paused until payment.")}<br />
              {L("ما زال متاحاً لك: مراجعة واعتماد زياراتك القائمة، وسجل الزيارات للقراءة.",
                 "Still available to you: reviewing and approving your existing visits, plus read-only visit history.")}
            </p>
            <p style={{ fontSize: 12.5, color: "#5c7096" }}>{L("التعليق الكامل يوم 30 · البيانات محفوظة 90 يوماً ثم تُصدَّر وتُحذف وفق PDPL.", "Full suspension on day 30 · data retained for 90 days, then exported and deleted per PDPL.")}</p>
            <Link href="/doctor" className="btn-secondary" style={{ textDecoration: "none", display: "inline-flex" }}>{L("العودة للرئيسة", "Back to home")}</Link>
          </div>
        ) : null}

        {phase === "patient" && resumeCandidate !== null ? (
          <div className="card" style={{ marginBottom: 14, borderInlineStart: "4px solid var(--m-info)",
                                         display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 240 }}>
              <strong>{L("تسجيل منقطع لم يكتمل", "Interrupted recording found")}</strong>
              <div className="page-desc" style={{ margin: 0 }}>
                {L(`زيارة ${resumeCandidate.patientName || "مريض"} ما تزال قيد التسجيل — الصوت السابق محفوظ على الخادم ويمكن الاستئناف من حيث توقف.`,
                   `A visit for ${resumeCandidate.patientName || "a patient"} is still recording — earlier audio is safe on the server; you can resume where it stopped.`)}
              </div>
            </div>
            <button className="btn btn-primary" onClick={() => void resumeRecording()}>
              {L("استئناف التسجيل", "Resume recording")}
            </button>
            <button className="btn" onClick={dismissResume}>{L("تجاهل", "Dismiss")}</button>
          </div>
        ) : null}

        {phase === "patient" ? (
          <div style={{ display: "grid", gridTemplateColumns: "1.2fr .9fr", gap: 16, alignItems: "start" }}>
            <section>
              <h1 className="page-title" style={{ display: "flex", gap: 8, alignItems: "center" }}>{L("بدء زيارة — اختيار المريض", "Start a visit — select patient")} <SpecBadge id="W-210" /></h1>
              <p className="page-desc">{L("عند الاختيار تُجلب لقطة الملف التاريخي كسياق للتحليل (FR-601).", "On selection, a snapshot of the patient's history is fetched as context for analysis (FR-601).")}</p>
              <div className="badge success" style={{ marginBottom: 10 }}>
                <span style={{ width: 8, height: 8, borderRadius: 999, background: "#12a594" }} />
                {L("قائمة المرضى مُزامنة من نظام المستشفى — ويمكنك إضافة مريض لم تصله المزامنة بعد",
                   "Patient list is synced from the hospital system — you may also add a patient the sync has not delivered yet")}
              </div>
              <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                <input className="field search" placeholder={L("ابحث بالاسم أو رقم الملف MRN…", "Search by name or MRN…")} value={query}
                  onChange={(event) => setQuery(event.target.value)} style={{ flex: 1, marginBottom: 0 }} />
                <button className="btn-secondary" style={{ whiteSpace: "nowrap" }}
                  onClick={() => { setAddForm({ ...EMPTY_PATIENT_FORM, hospital_mrn: /^\d+$/.test(query.trim()) ? query.trim() : "" }); setAddOpen(true); }}>
                  + {L("إضافة مريض", "Add patient")}
                </button>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 420, overflowY: "auto" }}>
                {patients.length === 0 ? (
                  <div className="grid-empty">
                    {L("لا نتائج — البحث بالاسم أو MRN داخل منشأتك فقط.", "No results — search by name or MRN within your facility only.")}<br />
                    {L("المريض غير موجود؟ الأصل أن يُسجَّل في نظام المستشفى ويظهر هنا مع المزامنة، ويمكنك إضافته الآن بزر «إضافة مريض» ليبدأ التسجيل فوراً.",
                       "Patient not found? They should normally be registered in the hospital system and arrive with the sync — or add them now with “Add patient” to start recording immediately.")}
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
                        <span style={{ display: "block", fontSize: 12.5, color: "#5c7096" }}>
                          {patient.gender ?? "—"} · {L("ملف", "MRN")} <bdi>{patient.hospital_mrn}</bdi>
                          {patient.source === "manual" ? ` · ${L("مضاف يدوياً", "Added manually")}` : ""}
                        </span>
                      </span>
                      <span className="badge" style={{ background: selected ? "#e6f7f4" : "#f7f9fb", color: selected ? "#12a594" : "#5c7096" }}>
                        {selected ? L("محدد ✓", "Selected ✓") : L("اختيار", "Select")}
                      </span>
                    </button>
                  );
                })}
              </div>
            </section>
            <aside style={{ position: "sticky", top: 120 }}>
              {selectedPatient !== null ? (
                <div className="card" style={{ border: "1.5px solid #00736d" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <strong style={{ fontSize: 16, flex: 1 }}>{L("موجز ملف المريض", "Patient file summary")}</strong>
                    <span className="tech-badge">patient_context_snapshot</span>
                  </div>
                  <p style={{ margin: "10px 0 2px", fontWeight: 700 }}>{selectedPatient.display_name}</p>
                  <p style={{ margin: 0, fontSize: 12.5, color: "#5c7096" }}>
                    {selectedPatient.gender ?? "—"} · {L("ملف", "MRN")} <bdi>{selectedPatient.hospital_mrn}</bdi> ·{" "}
                    {selectedPatient.source === "manual"
                      ? L("أُضيف يدوياً", "Added manually")
                      : L("مزامنة", "Synced")} {selectedPatient.synced_at.slice(0, 10)}
                  </p>
                  {selectedPatient.source === "manual" ? (
                    <p style={{ fontSize: 12, color: "#9c6f00", margin: "8px 0 0" }}>
                      {L("ملف أُنشئ داخل Medify — تأكد من مطابقة رقم الملف MRN لنظام المستشفى قبل رفع المذكرة.",
                         "File created inside Medify — verify the MRN matches the hospital system before the note is uploaded.")}
                    </p>
                  ) : null}
                  <p style={{ fontSize: 12.5, color: "#5c7096", margin: "10px 0 0" }}>
                    {L("اللقطة بتاريخها تُحفظ لكل زيارة — قابلية تدقيق ما رآه الـ", "A dated snapshot is stored per visit — auditability of what the ")}<bdi>AI</bdi>{L(" (DOC-04 §٤).", " saw (DOC-04 §4).")}{" "}
                    {L("تُجلب اللقطة الكاملة (المزمنة/الأدوية/الحساسيات/النتائج) عند إنشاء الزيارة.",
                       "The full snapshot (chronic conditions/medications/allergies/results) is fetched when the visit is created.")}
                  </p>
                  <button className="btn" style={{ width: "100%", marginTop: 14 }} onClick={() => setPhase("template")}>
                    {L("التالي: اختيار القالب", "Next: choose template")}
                  </button>
                </div>
              ) : (
                <div style={{ border: "2px dashed #c7d1e0", borderRadius: 12, padding: 24, textAlign: "center", color: "#5c7096", fontSize: 14 }}>
                  {L("اختر مريضاً لعرض موجز ملفه", "Select a patient to view their file summary")}<br />
                  <span style={{ fontSize: 12.5 }}>{L("الاسم وMRN للاختيار فقط — لقطة الملف ضمن زيارتك أنت (DOC-06 §٣)", "Name and MRN for selection only — the file snapshot stays within your own visit (DOC-06 §3)")}</span>
                </div>
              )}
            </aside>
          </div>
        ) : null}

        {phase === "template" ? (
          <section style={{ maxWidth: 620, margin: "0 auto" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <button className="btn-ghost" onClick={() => setPhase("patient")}>{L("→ المريض", "← Patient")}</button>
              <h1 className="page-title" style={{ margin: 0, flex: 1, display: "flex", gap: 8, alignItems: "center" }}>
                {L("اختيار قالب التلخيص", "Choose summary template")} <SpecBadge id="W-211" />
              </h1>
              <span style={{ fontSize: 12.5, color: "#5c7096" }}>{L("المريض:", "Patient:")} {selectedPatient?.display_name}</span>
            </div>
            <p className="page-desc">{L("الاختيار إلزامي قبل بدء التسجيل (FR-501) — قالبك الافتراضي محدد مسبقاً.", "Selection is required before recording starts (FR-501) — your default template is preselected.")}</p>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {templates.filter((template) => template.archived_at === null).map((template) => {
                const selected = selectedTemplate?.id === template.id;
                return (
                  <button key={template.id} className={selected ? "select-card selected" : "select-card"} onClick={() => setSelectedTemplate(template)}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <strong style={{ flex: 1 }}>{template.name}</strong>
                      {template.is_default ? <span className="badge" style={{ background: "rgba(0,194,184,.15)", color: "#9c6f00" }}>{L("الافتراضي", "Default")}</span> : null}
                      {template.origin === "reverse_built" ? <span className="badge" style={{ background: "rgba(0,194,184,.15)", color: "#9c6f00" }}>{L("بناء عكسي", "Reverse build")}</span> : null}
                      {template.is_personal ? <span className="badge info">{L("شخصي", "Personal")}</span> : <span className="badge neutral">{L("جاهز", "Preset")}</span>}
                    </div>
                    <div style={{ fontSize: 12.5, color: "#5c7096", marginTop: 4 }}>
                      {template.specialty ?? "—"} · {template.visit_type ?? "—"} · <span className="num">{template.structure.sections.length}</span> {L("أقسام", "sections")}
                    </div>
                  </button>
                );
              })}
            </div>
            <button className="btn hero" style={{ width: "100%", marginTop: 16 }} onClick={() => void proceedToConsent()}>
              {L("التالي — موافقة المريض", "Next — patient consent")}
            </button>
          </section>
        ) : null}

        {/* بوابة موافقة المريض (A1) — إلزامية قبل أي تسجيل */}
        {phase === "consent" && consent !== null ? (
          <section style={{ maxWidth: 640, margin: "0 auto" }}>
            <div className="card pad24">
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                <strong style={{ fontSize: 16, flex: 1 }}>{L("موافقة المريض على التسجيل", "Patient consent to record")}</strong>
                <span className="badge warn">{L("إلزامية قبل التسجيل", "Required before recording")}</span>
              </div>
              <p style={{ fontSize: 12.5, color: "#5c7096", margin: "0 0 12px" }}>
                {L("اقرأ النص للمريض شفهياً، وأكّد موافقته. لا يبدأ التسجيل قبل هذه الخطوة (MDF-4230).",
                   "Read the text to the patient, and confirm their consent. Recording cannot start before this step (MDF-4230).")}
              </p>
              <div className="card" style={{ background: "#f4f8fb", lineHeight: 1.9 }}>
                <p className="clinical" style={{ margin: 0 }}>{consent.document.text_ar}</p>
                <p dir="ltr" style={{ margin: "10px 0 0", fontSize: 13, color: "#33465f" }}>{consent.document.text_en}</p>
              </div>
              <label style={{ display: "flex", gap: 10, alignItems: "flex-start", marginTop: 14, cursor: "pointer" }}>
                <input type="checkbox" checked={consentAck} onChange={(event) => setConsentAck(event.target.checked)}
                  style={{ width: 18, height: 18, marginTop: 2 }} />
                <span style={{ fontSize: 13.5 }}>
                  {L(consent.document.ack_ar, consent.document.ack_en)}
                  <br />
                  <span style={{ fontSize: 12, color: "#5c7096" }}>
                    {L("الملتقط:", "Captured by:")} <strong>{getSessionUser()?.full_name ?? "—"}</strong>
                    {" · "}
                    <bdi className="ui">{consent.document.version}</bdi>
                  </span>
                </span>
              </label>
              <p style={{ fontSize: 12, color: "#5c7096", margin: "12px 0 0" }}>
                {L("عند التأكيد يطلب المتصفح إذن الميكروفون — الصوت يُبثّ عبر قناة الزيارة المشفّرة ويُفرَّغ كاملاً بعد إنهاء المحادثة، ولا يبدأ التسجيل قبل السماح.",
                   "On confirmation the browser will ask for microphone access — audio streams over the encrypted visit channel and is transcribed in full after the conversation ends; recording will not start before you allow it.")}
              </p>
              <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
                <button className="btn hero" style={{ flex: 1 }} disabled={!consentAck || consentBusy}
                  onClick={() => void confirmConsentAndRecord()}>
                  <span style={{ width: 10, height: 10, borderRadius: 999, background: "#fbeaea", animation: "mBlink 1.1s ease infinite" }} />
                  {consentBusy ? L("يُوثّق…", "Recording consent…") : L("وثّق الموافقة وابدأ التسجيل", "Record consent & start")}
                </button>
                <button className="btn-neutral" onClick={() => setPhase("template")}>{L("رجوع", "Back")}</button>
              </div>
            </div>
          </section>
        ) : null}

        {phase === "recording" ? (
          <section style={{ maxWidth: 620, margin: "0 auto" }}>
            <div className="card pad24" style={{ border: online ? "1px solid #c7d1e0" : "2px solid #9c6f00" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <SpecBadge id={online ? "W-212" : "W-223"} />
                <strong style={{ flex: 1 }}>{visit?.patient.display_name} · {L("قالب:", "Template:")} {visit?.template.name}</strong>
                <span className={online ? "badge success" : "badge danger"}>
                  <span style={{ width: 8, height: 8, borderRadius: 999, background: "currentColor" }} />
                  {online ? L("متصل", "Online") : L("غير متصل", "Offline")}
                </span>
              </div>
              {!online ? (
                <div style={{ background: "#fdf4e0", border: "1px solid #9c6f00", borderRadius: 10, padding: "10px 14px", margin: "12px 0 0", fontSize: 12.5, color: "#9c6f00", fontWeight: 700 }}>
                  {L("انقطاع الشبكة (", "Network interruption (")}<bdi>MDF-5031</bdi>{L(") — وضع الحفظ المحلي: ", ") — local save mode: ")}<span className="num">{offlineChunks}</span>{L(" جزءاً بانتظار الإرسال، يُستأنف من آخر جزء مؤكد تلقائياً (NFR-09).",
                    " chunks pending send — resumes automatically from the last confirmed chunk (NFR-09).")}
                </div>
              ) : null}
              <div style={{ marginTop: 12 }}>
                <UploadStatus
                  state={connState}
                  pendingChunks={offlineChunks}
                  bufferSizeKb={Math.round(offlineChunks * 10.7)}
                  onlineChunks={ackedChunks}
                  showDetails={connState !== "connected"}
                />
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 16, margin: "16px 0" }}>
                <span style={{ width: 12, height: 12, borderRadius: 999, background: "#d94b4b", animation: paused ? undefined : "mBlink 1.2s ease infinite" }} />
                <bdi style={{ fontSize: 28, fontWeight: 800, color: "#005a55" }}>{mm}:{ss}</bdi>
                {/* الأعمدة من ذروات الميكروفون الفعلية — خط مسطّح = لا يصل صوت */}
                <div className="wave" style={{ flex: 1, opacity: paused ? 0.3 : 1 }}>
                  {levels.map((level, index) => (
                    <span key={index} style={{
                      animation: "none",
                      height: `${Math.max(5, Math.min(100, Math.round(level * 260)))}%`,
                      background: micSilent ? "#c7d1e0" : undefined,
                      transition: "height .18s ease",
                    }} />
                  ))}
                </div>
              </div>
              {micSilent && !paused ? (
                <div style={{ background: "#fbeaea", border: "2px solid #d94b4b", borderRadius: 10, padding: "10px 14px", margin: "0 0 12px", fontSize: 13, color: "#a13333", lineHeight: 1.9 }}>
                  <strong>⚠ {L("الميكروفون لا يلتقط أي صوت", "The microphone is not picking up any audio")}</strong>
                  {" — "}
                  {L("الجهاز المستخدم:", "Device in use:")} <bdi>{mic.current?.deviceLabel !== "" ? mic.current?.deviceLabel : L("غير معروف", "unknown")}</bdi>
                  <br />
                  {L("لن يُبنى تفريغ ولا ملخص بعد الإنهاء ما دام الصوت لا يصل. تحقق من: زر كتم المايك في الجهاز/السماعة · اختيار الميكروفون الصحيح في إعدادات الموقع بالمتصفح · مستوى الإدخال في إعدادات صوت ويندوز.",
                     "No transcript or summary can be produced after finishing while no audio arrives. Check: the hardware mute button on your device/headset · the microphone selected in the browser's site settings · the input level in Windows sound settings.")}
                </div>
              ) : null}
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button className="btn-secondary" onClick={() => void togglePause()}>{paused ? L("استئناف", "Resume") : L("إيقاف مؤقت", "Pause")}</button>
                <button className="btn hero" style={{ flex: 1 }} onClick={() => void finishRecording()}>{L("إنهاء التسجيل وتوليد الملخص", "Finish recording & generate summary")}</button>
                <button className="btn-danger-outline" onClick={() => setCancelOpen(true)}>{L("إلغاء الزيارة", "Cancel visit")}</button>
              </div>
            </div>

            <div className="card" style={{ marginTop: 14, background: "#f4f8fb" }}>
              <strong style={{ fontSize: 16 }}>{L("التفريغ بعد إنهاء المحادثة", "Transcription after the conversation ends")}</strong>
              <p style={{ fontSize: 13, color: "#33465f", lineHeight: 1.9, margin: "8px 0 0" }}>
                {L("أثناء التسجيل يُجمع الصوت فقط — لا نص يظهر هنا عمداً. عند الإنهاء تُفرَّغ المحادثة كاملة تمريرة واحدة ويُحدَّد المتحدث (الطبيب/المريض) من كامل سياقها، فتكون دقة النص والإسناد أعلى من أي تفريغ لحظي مقطّع.",
                   "While recording, only audio is collected — no text appears here by design. On finish, the whole conversation is transcribed in a single pass and each speaker (doctor/patient) is identified from its full context, which is more accurate than chunked live transcription.")}
              </p>
              <p style={{ fontSize: 12, color: "#5c7096", margin: "8px 0 0" }}>
                {L("ركّز على مريضك — النص الكامل يظهر في شاشة المراجعة بعد الإنهاء (قرار مالك 2026-08-02).",
                   "Focus on your patient — the full transcript appears on the review screen after finishing (owner decision 2026-08-02).")}
              </p>
            </div>
          </section>
        ) : null}

        {phase === "generating" ? (
          <section style={{ maxWidth: 620, margin: "40px auto" }}>
            <div className="card pad24" style={{ textAlign: "center" }}>
              <SpecBadge id="W-213" />
              <h1 style={{ fontSize: 22, fontWeight: 800, margin: "10px 0 20px" }}>{L("جارٍ تفريغ المحادثة وتوليد الملخص", "Transcribing the conversation and generating the summary")}</h1>
              {[
                { label: L("تفريغ المحادثة كاملة وتحديد المتحدثين", "Full-conversation transcription & speaker identification"), sub: L("خط المعالجة P1 — تمريرة واحدة على التسجيل كله", "Pipeline P1 — a single pass over the whole recording"), state: genStep >= 1 ? "done" : "run" },
                { label: L("تلخيص وفق القالب + حذف ما لا سند له", "Template summary + removal of unsupported content"), sub: L("خط المعالجة P2 مع تمريرة السند", "Pipeline P2 with the evidence pass"), state: genStep >= 2 ? "done" : genStep === 1 ? "run" : "wait" },
                { label: L("التحليل الذكي المدمج — سريري + ترميزي", "Integrated AI analysis — clinical + coding"), sub: L("خط المعالجة P3 على ملف المريض + كلام الزيارة", "Pipeline P3 over the patient file + visit speech"), state: genStep === 3 ? "done" : genStep === 2 ? "run" : "wait" },
              ].map((step) => (
                <div key={step.label} style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 8px", borderTop: "1px solid #d6f5f2", textAlign: "start" }}>
                  {step.state === "done" ? (
                    <span style={{ width: 26, height: 26, borderRadius: 999, background: "#12a594", color: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", fontWeight: 800 }}>✓</span>
                  ) : step.state === "run" ? (
                    <span className="spinner dark" style={{ width: 22, height: 22 }} />
                  ) : (
                    <span style={{ width: 26, height: 26, borderRadius: 999, border: "2px solid #c7d1e0" }} />
                  )}
                  <span style={{ flex: 1 }}>
                    <strong>{step.label}</strong>
                    <span style={{ display: "block", fontSize: 12.5, color: "#5c7096" }}>
                      {step.sub} — {step.state === "done" ? L("اكتمل", "Completed") : step.state === "run" ? L("يجري الآن…", "Running now…") : L("في الانتظار", "Waiting")}
                    </span>
                  </span>
                </div>
              ))}
              <p style={{ fontSize: 12.5, color: "#5c7096", marginTop: 14 }}>{L("المحادثة تُفرَّغ كاملة أولاً ثم يُبنى الملخص — فشل التحليل لا يحجب الملخص (W-224).", "The whole conversation is transcribed first, then the summary is built — analysis failure does not block the summary (W-224).")}</p>
            </div>
          </section>
        ) : null}

        {addOpen ? (
          <Modal title={L("إضافة مريض", "Add patient")} onClose={() => { if (!addBusy) setAddOpen(false); }}>
            <p style={{ fontSize: 12.5, color: "#5c7096", margin: "0 0 12px" }}>
              {L("للمريض الذي لم يصل بعد من مزامنة نظام المستشفى. اكتب رقم الملف MRN كما هو في نظام المستشفى — عليه يُبنى رفع المذكرة لاحقاً.",
                 "For a patient the hospital sync has not delivered yet. Enter the MRN exactly as in the hospital system — the note upload is keyed to it.")}
            </p>
            <Field label={L("رقم الملف MRN *", "MRN *")} ltr value={addForm.hospital_mrn} autoFocus
              placeholder="1042376"
              onChange={(event) => setAddForm({ ...addForm, hospital_mrn: event.target.value })} />
            <Field label={L("الاسم الكامل *", "Full name *")} value={addForm.display_name}
              placeholder={L("محمد عبدالله القحطاني", "Mohammed Abdullah Alqahtani")}
              onChange={(event) => setAddForm({ ...addForm, display_name: event.target.value })} />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div>
                <Field label={L("تاريخ الميلاد", "Date of birth")} ltr type="date" value={addForm.dob}
                  onChange={(event) => setAddForm({ ...addForm, dob: event.target.value })} />
              </div>
              <div>
                <label className="field-label">{L("الجنس", "Gender")}</label>
                <select className="field" value={addForm.gender}
                  onChange={(event) => setAddForm({ ...addForm, gender: event.target.value })}>
                  <option value="">{L("غير محدد", "Unspecified")}</option>
                  <option value="ذكر">{L("ذكر", "Male")}</option>
                  <option value="أنثى">{L("أنثى", "Female")}</option>
                </select>
              </div>
            </div>
            <p style={{ fontSize: 12, color: "#5c7096", margin: "12px 0 0" }}>
              {L("يُحفظ داخل منشأتك فقط، والاسم وتاريخ الميلاد مشفّران في القاعدة (DOC-16).",
                 "Stored within your facility only; name and date of birth are encrypted at rest (DOC-16).")}
            </p>
            <div className="modal-actions">
              <button className="btn" style={{ flex: 1 }} disabled={addBusy} onClick={() => void submitNewPatient()}>
                {addBusy ? L("يُضاف…", "Adding…") : L("إضافة واختيار", "Add & select")}
              </button>
              <button className="btn-neutral" style={{ flex: 1 }} disabled={addBusy} onClick={() => setAddOpen(false)}>
                {L("إلغاء", "Cancel")}
              </button>
            </div>
          </Modal>
        ) : null}

        {cancelOpen ? (
          <Modal title={L("إلغاء الزيارة", "Cancel visit")} onClose={() => setCancelOpen(false)}>
            <div style={{ textAlign: "center" }}>
              <div style={{ width: 52, height: 52, borderRadius: 999, background: "#fbeaea", display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#d94b4b" strokeWidth="2"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
              </div>
              <p style={{ fontSize: 14, margin: "12px 0" }}>
                {L("الإلغاء متاح أثناء التسجيل فقط — حالة نهائية ", "Cancellation is available during recording only — final state ")}<bdi>cancelled</bdi>{L(": لا اعتماد ولا رفع، ويُحذف التسجيل (قرار مالك 2026-07-14).", ": no approval, no upload, and the recording is deleted (owner decision 2026-07-14).")}
              </p>
            </div>
            <div className="modal-actions">
              <button className="btn-danger" style={{ flex: 1 }} onClick={() => void cancelVisit()}>{L("تأكيد الإلغاء", "Confirm cancellation")}</button>
              <button className="btn-neutral" style={{ flex: 1 }} onClick={() => setCancelOpen(false)}>{L("متابعة التسجيل", "Continue recording")}</button>
            </div>
          </Modal>
        ) : null}

        {phase === "patient" && context !== null ? null : null}
      </main>
    </Shell>
  );
}
