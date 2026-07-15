"use client";

/** الصفحة 7 — المقاعد والفوترة W-105/W-111/W-208: تبويبا المقاعد والفواتير (FR-102 · DOC-09). */

import { useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { Modal, SpecBadge, SpecBar, Tabs, fmtDateTime, useToast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import type { Lang } from "@/lib/i18n";
import type { Invoice, SubscriptionInfo } from "@/lib/types";

type LFn = (ar: string, en: string) => string;

/* الحدث ثنائي اللغة — مفاتيح seat_events (DOC-04) */
const SEAT_REASON: Record<string, { ar: string; en: string }> = {
  expand: { ar: "توسعة", en: "Expansion" },
  reduce: { ar: "تقليص", en: "Reduction" },
  activate_dr: { ar: "تفعيل دكتور", en: "Doctor activated" },
  deactivate_dr: { ar: "تعطيل دكتور", en: "Doctor deactivated" },
};

const INVOICE_STATUS: Record<Invoice["status"], { label: { ar: string; en: string }; cls: string }> = {
  paid: { label: { ar: "مسددة", en: "Paid" }, cls: "badge success" },
  due: { label: { ar: "مستحقة", en: "Due" }, cls: "badge warn" },
  overdue: { label: { ar: "متأخرة", en: "Overdue" }, cls: "badge danger" },
  void: { label: { ar: "ملغاة", en: "Void" }, cls: "badge neutral" },
};

const SEAT_COLS = "1.2fr 1.8fr .6fr";
const INVOICE_COLS = "1.2fr 1.5fr .9fr .9fr 1fr .9fr .8fr";

function fmtSar(value: string): string {
  const num = Number(value);
  if (Number.isNaN(num)) return value;
  return num.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function apiErrorText(err: unknown, lang: Lang, L: LFn): string {
  return err instanceof ApiError ? `${err.text(lang)} (${err.code})` : L("تعذر الاتصال بالخادم", "Could not reach the server");
}

/* ===== تبويب «المقاعد» W-105 ===== */
function SeatsTab({ info, reload }: { info: SubscriptionInfo; reload: () => Promise<void> }) {
  const toast = useToast();
  const { L, lang } = useLang();
  const [newTotal, setNewTotal] = useState(info.seats_total);
  const [busy, setBusy] = useState(false);

  useEffect(() => { setNewTotal(info.seats_total); }, [info.seats_total]);

  const apply = async () => {
    if (newTotal === info.seats_total) {
      toast(L("لا تغيير في عدد المقاعد", "No change in seat count"));
      return;
    }
    setBusy(true);
    try {
      const delta = newTotal - info.seats_total;
      await api("/subscription/seats", { method: "PATCH", body: { seats_total: newTotal } });
      toast(delta > 0
        ? L(`وُسّعت المقاعد فوراً (+${delta}) — فوترة تناسبية (FR-102)`,
            `Seats expanded immediately (+${delta}) — prorated billing (FR-102)`)
        : L(`قُلّص الإجمالي (${delta}) — يسري بداية الدورة التالية (DOC-09 §٢)`,
            `Total reduced (${delta}) — effective at the start of the next cycle (DOC-09 §2)`));
      await reload();
    } catch (err) {
      toast(apiErrorText(err, lang, L));
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
          <div className="stat-label">{L("إجمالي المقاعد — توسعة / تقليص", "Total seats — expand / reduce")}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6 }}>
            <button type="button" aria-label={L("إنقاص", "Decrease")} style={stepBtn} onClick={() => setNewTotal((value) => Math.max(1, value - 1))}>−</button>
            <span className="num" style={{ fontSize: 28, fontWeight: 800, color: "#0A5C64", minWidth: 36, textAlign: "center" }}>{newTotal}</span>
            <button type="button" aria-label={L("زيادة", "Increase")} style={stepBtn} onClick={() => setNewTotal((value) => Math.min(50, value + 1))}>+</button>
          </div>
          <div style={{ fontSize: 12.5, color: "#5B7280", margin: "6px 0 10px" }}>
            {L("الحالي:", "Current:")} <span className="num">{info.seats_total}</span> {L("— كل دكتور نشط يستهلك مقعداً (FR-202)", "— each active doctor consumes a seat (FR-202)")}
          </div>
          <button className="btn h40" onClick={() => void apply()} disabled={busy}>
            {busy ? <span className="spinner" /> : null} {L("تطبيق", "Apply")}
          </button>
        </div>
        <div className="card">
          <div className="stat-label">{L("المستهلكة", "Used")}</div>
          <div className="stat-value num">{info.seats_used}</div>
        </div>
        <div className="card">
          <div className="stat-label">{L("المتاحة", "Available")}</div>
          <div className="stat-value num" style={{ color: "#2E9E5B" }}>{info.seats_available}</div>
        </div>
        <div className="card">
          <div className="stat-label">{L("الخطة", "Plan")}</div>
          <div className="stat-value">{info.plan === "monthly" ? L("شهرية", "Monthly") : info.plan === "yearly" ? L("سنوية", "Yearly") : info.plan}</div>
        </div>
      </div>

      <div className="info-box" style={{ marginTop: 14 }}>
        {L("التوسعة فورية بفوترة تناسبية · التقليص بداية الدورة التالية · تعطيل دكتور يحرر المقعد فوراً (DOC-09 §٢)",
           "Expansion is immediate with prorated billing · reduction takes effect at the start of the next cycle · deactivating a doctor frees the seat immediately (DOC-09 §2)")}
      </div>

      <h2 style={{ fontSize: 16, fontWeight: 700, margin: "22px 0 10px", display: "flex", alignItems: "center", gap: 8 }}>
        {L("سجل أحداث المقاعد", "Seat event log")} <span className="tech-badge">seat_events</span>
      </h2>
      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: SEAT_COLS }}>
          <div>{L("الوقت", "Time")}</div><div>{L("الحدث", "Event")}</div><div>{L("التغير", "Change")}</div>
        </div>
        {info.seat_events.length === 0 ? (
          <div className="grid-empty">{L("لا أحداث مقاعد بعد", "No seat events yet")}</div>
        ) : (
          info.seat_events.map((event, i) => {
            const reason = SEAT_REASON[event.reason];
            return (
              <div key={event.id} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: SEAT_COLS }}>
                <div>{fmtDateTime(event.at)}</div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  {reason !== undefined ? L(reason.ar, reason.en) : event.reason}
                  <span className="tech-badge">{event.reason}</span>
                </div>
                <div className="num" style={{ fontWeight: 700, color: event.delta > 0 ? "#2E9E5B" : event.delta < 0 ? "#B07D10" : "#5B7280" }}>
                  {event.delta > 0 ? `+${event.delta}` : event.delta}
                </div>
              </div>
            );
          })
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
  const { L, lang } = useLang();
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
        setError(L("لم تكتمل عملية السداد لدى المزود — أعد المحاولة", "The provider did not complete the payment — please retry"));
      }
    } catch (err) {
      setStage("idle");
      setError(apiErrorText(err, lang, L));
    }
  };

  const line = { display: "flex", justifyContent: "space-between", marginTop: 4 } as const;

  return (
    <Modal title={L("سداد الفاتورة", "Pay invoice")} spec="W-208" onClose={onClose}>
      {stage === "paid" ? (
        <div style={{ textAlign: "center" }}>
          <div style={{ width: 56, height: 56, borderRadius: 999, background: "#E8F6EE", display: "inline-flex", alignItems: "center", justifyContent: "center", color: "#2E9E5B", fontSize: 24, fontWeight: 800 }}>✓</div>
          <h3 style={{ fontSize: 18, fontWeight: 700, color: "#0A5C64", margin: "12px 0 6px" }}>{L("تم السداد بنجاح", "Payment successful")}</h3>
          <p style={{ fontSize: 14, color: "#5B7280", margin: "0 0 14px" }}>
            {L("الإيصال:", "Receipt:")} <bdi>{receipt}</bdi> {L("— سُجّلت العملية في سجل التدقيق", "— the operation was recorded in the audit log")} (<bdi>invoice.paid</bdi>)
          </p>
          <button className="btn" onClick={onClose}>{L("إغلاق", "Close")}</button>
        </div>
      ) : (
        <>
          <p style={{ fontSize: 12.5, color: "#5B7280", margin: "0 0 10px" }}>{L("الفاتورة", "Invoice")} <bdi>{invoice.number}</bdi></p>
          <div className="sub-box" style={{ fontSize: 14 }}>
            <div style={{ ...line, marginTop: 0 }}>
              <span>{L("المبلغ قبل الضريبة", "Amount before VAT")}</span>
              <bdi>{fmtSar(invoice.amount_sar)} SAR</bdi>
            </div>
            <div style={line}>
              <span>{L("ضريبة القيمة المضافة 15% — مفصولة", "VAT 15% — itemized")}</span>
              <bdi>{fmtSar(invoice.vat_sar)} SAR</bdi>
            </div>
            <div style={{ ...line, fontWeight: 700 }}>
              <span>{L("الإجمالي", "Total")}</span>
              <bdi>{fmtSar(invoice.total_sar)} SAR</bdi>
            </div>
          </div>
          <div className="info-box" style={{ marginTop: 12 }}>
            {L("مزود دفع محلي بالريال —", "Local SAR payment provider —")} <bdi>Moyasar</bdi>/<bdi>Tap</bdi> {L("يُقفل بعد اختبار حقيقي (DOC-09 §٣)", "finalized after a live test (DOC-09 §3)")}
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
              <><span className="spinner" /> {L("جارٍ معالجة الدفع عبر المزود المحلي…", "Processing payment via the local provider…")}</>
            ) : error !== null ? L("إعادة المحاولة", "Retry") : L("تأكيد الدفع", "Confirm payment")}
          </button>
        </>
      )}
    </Modal>
  );
}

/* ===== تبويب «الفواتير والسداد» W-111 ===== */
function InvoicesTab() {
  const toast = useToast();
  const { L, lang } = useLang();
  const [rows, setRows] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [paying, setPaying] = useState<Invoice | null>(null);

  const load = useCallback(async () => {
    try {
      const body = await api<Invoice[]>("/invoices");
      setRows(body.data);
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setLoading(false);
    }
  }, [toast, lang, L]);

  useEffect(() => { void load(); }, [load]);

  return (
    <>
      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: INVOICE_COLS }}>
          <div>{L("الفاتورة", "Invoice")}</div><div>{L("الفترة", "Period")}</div><div>{L("المبلغ", "Amount")}</div><div>{L("ضريبة 15%", "VAT 15%")}</div><div>{L("الإجمالي", "Total")}</div><div>{L("الحالة", "Status")}</div><div>{L("إجراء", "Action")}</div>
        </div>
        {loading ? (
          <div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div>
        ) : rows.length === 0 ? (
          <div className="grid-empty">{L("لا فواتير بعد", "No invoices yet")}</div>
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
                <div><span className={status.cls}>{L(status.label.ar, status.label.en)}</span></div>
                <div>
                  {payable ? (
                    <button className="btn-row" onClick={() => setPaying(invoice)}>{L("سداد", "Pay")}</button>
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
        {L("كل تغيّر مقاعد يظهر في فاتورة الدورة · الأسعار توضيحية — تُقفل بعد التحقق الميداني (DOC-09 §٤).",
           "Every seat change appears on the cycle invoice · prices are illustrative — finalized after field validation (DOC-09 §4).")}
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
  const { L, lang } = useLang();
  const [tab, setTab] = useState<"seats" | "invoices">("seats");
  const [info, setInfo] = useState<SubscriptionInfo | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const body = await api<SubscriptionInfo>("/subscription");
      setInfo(body.data);
    } catch (err) {
      toast(apiErrorText(err, lang, L));
    } finally {
      setLoading(false);
    }
  }, [toast, lang, L]);

  useEffect(() => { void load(); }, [load]);

  return (
    <>
      <SpecBar ids="W-105 · W-111 · W-208" desc={L("الصفحة 7 — تبويبان في صفحة اشتراك واحدة (FR-102 · DOC-09)", "Page 7 — two tabs in a single subscription page (FR-102 · DOC-09)")} />
      <Tabs
        tabs={[
          { key: "seats", label: <>{L("المقاعد", "Seats")} <SpecBadge id="W-105" /></> },
          { key: "invoices", label: <>{L("الفواتير والسداد", "Invoices & payment")} <SpecBadge id="W-111" /></> },
        ]}
        active={tab}
        onChange={setTab}
      />
      {tab === "seats" ? (
        loading ? (
          <div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div>
        ) : info === null ? (
          <div className="grid-empty">{L("تعذر تحميل بيانات الاشتراك", "Could not load subscription data")}</div>
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
  const { L } = useLang();
  return (
    <Shell title={L("المقاعد والفوترة", "Seats & billing")}>
      <main className="page-wrap narrow">
        <SubscriptionInner />
      </main>
    </Shell>
  );
}
