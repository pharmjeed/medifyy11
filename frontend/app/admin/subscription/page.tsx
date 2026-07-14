"use client";

/** الصفحة 7 — المقاعد والفوترة W-105/W-111/W-208: تبويبا المقاعد والفواتير (FR-102 · DOC-09). */

import { useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { Modal, SpecBadge, SpecBar, Tabs, fmtDateTime, useToast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Invoice, SubscriptionInfo } from "@/lib/types";

/* الحدث بالعربية — مفاتيح seat_events (DOC-04) */
const SEAT_REASON: Record<string, string> = {
  expand: "توسعة",
  reduce: "تقليص",
  activate_dr: "تفعيل دكتور",
  deactivate_dr: "تعطيل دكتور",
};

const INVOICE_STATUS: Record<Invoice["status"], { label: string; cls: string }> = {
  paid: { label: "مسددة", cls: "badge success" },
  due: { label: "مستحقة", cls: "badge warn" },
  overdue: { label: "متأخرة", cls: "badge danger" },
  void: { label: "ملغاة", cls: "badge neutral" },
};

const SEAT_COLS = "1.2fr 1.8fr .6fr";
const INVOICE_COLS = "1.2fr 1.5fr .9fr .9fr 1fr .9fr .8fr";

function fmtSar(value: string): string {
  const num = Number(value);
  if (Number.isNaN(num)) return value;
  return num.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function apiErrorText(err: unknown): string {
  return err instanceof ApiError ? `${err.messageAr} (${err.code})` : "تعذر الاتصال بالخادم";
}

/* ===== تبويب «المقاعد» W-105 ===== */
function SeatsTab({ info, reload }: { info: SubscriptionInfo; reload: () => Promise<void> }) {
  const toast = useToast();
  const [newTotal, setNewTotal] = useState(info.seats_total);
  const [busy, setBusy] = useState(false);

  useEffect(() => { setNewTotal(info.seats_total); }, [info.seats_total]);

  const apply = async () => {
    if (newTotal === info.seats_total) {
      toast("لا تغيير في عدد المقاعد");
      return;
    }
    setBusy(true);
    try {
      const delta = newTotal - info.seats_total;
      await api("/subscription/seats", { method: "PATCH", body: { seats_total: newTotal } });
      toast(delta > 0
        ? `وُسّعت المقاعد فوراً (+${delta}) — فوترة تناسبية (FR-102)`
        : `قُلّص الإجمالي (${delta}) — يسري بداية الدورة التالية (DOC-09 §٢)`);
      await reload();
    } catch (err) {
      toast(apiErrorText(err));
    } finally {
      setBusy(false);
    }
  };

  const stepBtn = {
    width: 40, height: 40, border: "1.5px solid #0E7C86", borderRadius: 10,
    background: "#fff", color: "#0A5C64", fontSize: 18, fontWeight: 700, cursor: "pointer",
  } as const;

  return (
    <>
      <div className="stat-grid">
        <div className="card" style={{ borderColor: "#0E7C86" }}>
          <div className="stat-label">إجمالي المقاعد — توسعة / تقليص</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6 }}>
            <button type="button" aria-label="إنقاص" style={stepBtn} onClick={() => setNewTotal((value) => Math.max(1, value - 1))}>−</button>
            <span className="num" style={{ fontSize: 28, fontWeight: 800, color: "#0A5C64", minWidth: 36, textAlign: "center" }}>{newTotal}</span>
            <button type="button" aria-label="زيادة" style={stepBtn} onClick={() => setNewTotal((value) => Math.min(50, value + 1))}>+</button>
          </div>
          <div style={{ fontSize: 12.5, color: "#5B7280", margin: "6px 0 10px" }}>
            الحالي: <span className="num">{info.seats_total}</span> — كل دكتور نشط يستهلك مقعداً (FR-202)
          </div>
          <button className="btn h40" onClick={() => void apply()} disabled={busy}>
            {busy ? <span className="spinner" /> : null} تطبيق
          </button>
        </div>
        <div className="card">
          <div className="stat-label">المستهلكة</div>
          <div className="stat-value num">{info.seats_used}</div>
        </div>
        <div className="card">
          <div className="stat-label">المتاحة</div>
          <div className="stat-value num" style={{ color: "#2E9E5B" }}>{info.seats_available}</div>
        </div>
        <div className="card">
          <div className="stat-label">الخطة</div>
          <div className="stat-value">{info.plan === "monthly" ? "شهرية" : info.plan === "yearly" ? "سنوية" : info.plan}</div>
        </div>
      </div>

      <div className="info-box" style={{ marginTop: 14 }}>
        التوسعة فورية بفوترة تناسبية · التقليص بداية الدورة التالية · تعطيل دكتور يحرر المقعد فوراً (DOC-09 §٢)
      </div>

      <h2 style={{ fontSize: 16, fontWeight: 700, margin: "22px 0 10px", display: "flex", alignItems: "center", gap: 8 }}>
        سجل أحداث المقاعد <span className="tech-badge">seat_events</span>
      </h2>
      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: SEAT_COLS }}>
          <div>الوقت</div><div>الحدث</div><div>التغير</div>
        </div>
        {info.seat_events.length === 0 ? (
          <div className="grid-empty">لا أحداث مقاعد بعد</div>
        ) : (
          info.seat_events.map((event, i) => (
            <div key={event.id} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: SEAT_COLS }}>
              <div>{fmtDateTime(event.at)}</div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                {SEAT_REASON[event.reason] ?? event.reason}
                <span className="tech-badge">{event.reason}</span>
              </div>
              <div className="num" style={{ fontWeight: 700, color: event.delta > 0 ? "#2E9E5B" : event.delta < 0 ? "#B07D10" : "#5B7280" }}>
                {event.delta > 0 ? `+${event.delta}` : event.delta}
              </div>
            </div>
          ))
        )}
      </div>
    </>
  );
}

/* ===== نافذة السداد W-208 ===== */
interface PayResult {
  status: string;
  provider_ref?: string;
  receipt?: string;
  checkout_url?: string;
}

function PayModal({ invoice, onClose, onPaid }: { invoice: Invoice; onClose: () => void; onPaid: () => void }) {
  const [stage, setStage] = useState<"idle" | "paying" | "paid">("idle");
  const [receipt, setReceipt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pay = async () => {
    setStage("paying");
    setError(null);
    try {
      const body = await api<PayResult>(`/invoices/${invoice.id}/pay`, { method: "POST" });
      if (body.data.status === "paid") {
        setReceipt(body.data.receipt ?? body.data.provider_ref ?? "");
        setStage("paid");
        onPaid();
      } else {
        setStage("idle");
        setError("لم تكتمل عملية السداد لدى المزود — أعد المحاولة");
      }
    } catch (err) {
      setStage("idle");
      setError(apiErrorText(err));
    }
  };

  const line = { display: "flex", justifyContent: "space-between", marginTop: 4 } as const;

  return (
    <Modal title="سداد الفاتورة" spec="W-208" onClose={onClose}>
      {stage === "paid" ? (
        <div style={{ textAlign: "center" }}>
          <div style={{ width: 56, height: 56, borderRadius: 999, background: "#E8F6EE", display: "inline-flex", alignItems: "center", justifyContent: "center", color: "#2E9E5B", fontSize: 24, fontWeight: 800 }}>✓</div>
          <h3 style={{ fontSize: 18, fontWeight: 700, color: "#0A5C64", margin: "12px 0 6px" }}>تم السداد بنجاح</h3>
          <p style={{ fontSize: 14, color: "#5B7280", margin: "0 0 14px" }}>
            الإيصال: <bdi>{receipt}</bdi> — سُجّلت العملية في سجل التدقيق (<bdi>invoice.paid</bdi>)
          </p>
          <button className="btn" onClick={onClose}>إغلاق</button>
        </div>
      ) : (
        <>
          <p style={{ fontSize: 12.5, color: "#5B7280", margin: "0 0 10px" }}>الفاتورة <bdi>{invoice.number}</bdi></p>
          <div className="sub-box" style={{ fontSize: 14 }}>
            <div style={{ ...line, marginTop: 0 }}>
              <span>المبلغ قبل الضريبة</span>
              <bdi>{fmtSar(invoice.amount_sar)} SAR</bdi>
            </div>
            <div style={line}>
              <span>ضريبة القيمة المضافة 15% — مفصولة</span>
              <bdi>{fmtSar(invoice.vat_sar)} SAR</bdi>
            </div>
            <div style={{ ...line, fontWeight: 700 }}>
              <span>الإجمالي</span>
              <bdi>{fmtSar(invoice.total_sar)} SAR</bdi>
            </div>
          </div>
          <div className="info-box" style={{ marginTop: 12 }}>
            مزود دفع محلي بالريال — <bdi>Moyasar</bdi>/<bdi>Tap</bdi> يُقفل بعد اختبار حقيقي (DOC-09 §٣)
          </div>
          {error !== null ? (
            <p style={{ color: "#C0392B", fontSize: 12.5, fontWeight: 700, margin: "12px 0 0" }}>{error}</p>
          ) : null}
          <button
            className="btn-success"
            style={{ width: "100%", height: 48, marginTop: 14 }}
            onClick={() => void pay()}
            disabled={stage === "paying"}
          >
            {stage === "paying" ? (
              <><span className="spinner" /> جارٍ معالجة الدفع عبر المزود المحلي…</>
            ) : error !== null ? "إعادة المحاولة" : "تأكيد الدفع"}
          </button>
        </>
      )}
    </Modal>
  );
}

/* ===== تبويب «الفواتير والسداد» W-111 ===== */
function InvoicesTab() {
  const toast = useToast();
  const [rows, setRows] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [paying, setPaying] = useState<Invoice | null>(null);

  const load = useCallback(async () => {
    try {
      const body = await api<Invoice[]>("/invoices");
      setRows(body.data);
    } catch (err) {
      toast(apiErrorText(err));
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { void load(); }, [load]);

  return (
    <>
      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: INVOICE_COLS }}>
          <div>الفاتورة</div><div>الفترة</div><div>المبلغ</div><div>ضريبة 15%</div><div>الإجمالي</div><div>الحالة</div><div>إجراء</div>
        </div>
        {loading ? (
          <div className="grid-empty">جارٍ التحميل…</div>
        ) : rows.length === 0 ? (
          <div className="grid-empty">لا فواتير بعد</div>
        ) : (
          rows.map((invoice, i) => {
            const status = INVOICE_STATUS[invoice.status];
            const payable = invoice.status === "due" || invoice.status === "overdue";
            return (
              <div key={invoice.id} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: INVOICE_COLS }}>
                <div><bdi>{invoice.number}</bdi></div>
                <div><bdi style={{ fontSize: 12.5 }}>{invoice.period_start.slice(0, 10)} → {invoice.period_end.slice(0, 10)}</bdi></div>
                <div><bdi>{fmtSar(invoice.amount_sar)}</bdi></div>
                <div><bdi>{fmtSar(invoice.vat_sar)}</bdi></div>
                <div style={{ fontWeight: 700 }}><bdi>{fmtSar(invoice.total_sar)}</bdi></div>
                <div><span className={status.cls}>{status.label}</span></div>
                <div>
                  {payable ? (
                    <button className="btn-row" onClick={() => setPaying(invoice)}>سداد</button>
                  ) : (
                    <span style={{ color: "#5B7280" }}>—</span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
      <p style={{ fontSize: 12.5, color: "#5B7280", margin: "10px 0 0" }}>
        كل تغيّر مقاعد يظهر في فاتورة الدورة · الأسعار توضيحية — تُقفل بعد التحقق الميداني (DOC-09 §٤).
      </p>
      {paying !== null ? (
        <PayModal invoice={paying} onClose={() => setPaying(null)} onPaid={() => { void load(); }} />
      ) : null}
    </>
  );
}

/* ===== الصفحة ===== */
function SubscriptionInner() {
  const toast = useToast();
  const [tab, setTab] = useState<"seats" | "invoices">("seats");
  const [info, setInfo] = useState<SubscriptionInfo | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const body = await api<SubscriptionInfo>("/subscription");
      setInfo(body.data);
    } catch (err) {
      toast(apiErrorText(err));
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { void load(); }, [load]);

  return (
    <>
      <SpecBar ids="W-105 · W-111 · W-208" desc="الصفحة 7 — تبويبان في صفحة اشتراك واحدة (FR-102 · DOC-09)" />
      <Tabs
        tabs={[
          { key: "seats", label: <>المقاعد <SpecBadge id="W-105" /></> },
          { key: "invoices", label: <>الفواتير والسداد <SpecBadge id="W-111" /></> },
        ]}
        active={tab}
        onChange={setTab}
      />
      {tab === "seats" ? (
        loading ? (
          <div className="grid-empty">جارٍ التحميل…</div>
        ) : info === null ? (
          <div className="grid-empty">تعذر تحميل بيانات الاشتراك</div>
        ) : (
          <SeatsTab info={info} reload={load} />
        )
      ) : (
        <InvoicesTab />
      )}
    </>
  );
}

export default function SubscriptionPage() {
  return (
    <Shell title="المقاعد والفوترة">
      <main className="page-wrap narrow">
        <SubscriptionInner />
      </main>
    </Shell>
  );
}
