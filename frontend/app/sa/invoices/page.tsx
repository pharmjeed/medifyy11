"use client";

/** فواتير المنصة كلها — تصفية بالحالة، تسجيل سداد يدوي وإلغاء، مع اسم المنشأة ورابطها. */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { SaShell } from "@/components/SaShell";
import { fmtDateTime, useToast } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { saApi } from "@/lib/sa";
import type { SaInvoice } from "@/lib/types";

const COLS = "1.1fr 1.3fr 1.2fr .8fr .9fr .8fr 1.1fr";

const INVOICE_STATUS: Record<SaInvoice["status"], { ar: string; en: string; cls: string }> = {
  paid: { ar: "مسددة", en: "Paid", cls: "badge success" },
  due: { ar: "مستحقة", en: "Due", cls: "badge warn" },
  overdue: { ar: "متأخرة", en: "Overdue", cls: "badge danger" },
  void: { ar: "ملغاة", en: "Void", cls: "badge neutral" },
};

function fmtSar(value: string): string {
  const num = Number(value);
  if (Number.isNaN(num)) return value;
  return num.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function InvoicesInner() {
  const params = useSearchParams();
  const toast = useToast();
  const { L, lang } = useLang();
  const [rows, setRows] = useState<SaInvoice[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState(params.get("status") ?? "");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  const errText = useCallback((err: unknown) => (
    err instanceof ApiError ? `${err.text(lang)} (${err.code})` : L("تعذر الاتصال بالخادم", "Could not reach the server")
  ), [lang, L]);

  const load = useCallback(async (searchStatus: string, searchPage: number) => {
    setLoading(true);
    try {
      const query = new URLSearchParams({ page: String(searchPage), per_page: "25" });
      if (searchStatus) query.set("status", searchStatus);
      const body = await saApi<SaInvoice[]>(`/invoices?${query.toString()}`);
      setRows(body.data);
      setTotal(body.meta.total ?? 0);
    } catch (err) {
      toast(errText(err));
    } finally {
      setLoading(false);
    }
  }, [toast, errText]);

  useEffect(() => { void load(status, page); }, [load, status, page]);

  const setInvoiceStatus = async (invoice: SaInvoice, newStatus: "paid" | "void") => {
    setBusy(invoice.id);
    try {
      await saApi(`/invoices/${invoice.id}`, { method: "PATCH", body: { status: newStatus } });
      toast(newStatus === "paid"
        ? L(`سُجّل سداد ${invoice.number}`, `${invoice.number} marked paid`)
        : L(`أُلغيت ${invoice.number}`, `${invoice.number} voided`));
      await load(status, page);
    } catch (err) {
      toast(errText(err));
    } finally {
      setBusy(null);
    }
  };

  const pages = Math.max(1, Math.ceil(total / 25));

  return (
    <>
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 14, flexWrap: "wrap" }}>
        <div className="tabs" role="tablist" style={{ margin: 0, flex: 1 }}>
          {[["", L("الكل", "All")], ["due", L("مستحقة", "Due")], ["overdue", L("متأخرة", "Overdue")], ["paid", L("مسددة", "Paid")], ["void", L("ملغاة", "Void")]].map(([key, label]) => (
            <button key={key} role="tab" aria-selected={status === key}
              className={status === key ? "tab active" : "tab"}
              onClick={() => { setStatus(key ?? ""); setPage(1); }}>{label}</button>
          ))}
        </div>
        <span style={{ fontSize: 13, color: "#5B7280" }}>
          {L("الإجمالي:", "Total:")} <span className="num">{total}</span>
        </span>
      </div>

      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: COLS }}>
          <div>{L("الفاتورة", "Invoice")}</div><div>{L("المنشأة", "Facility")}</div><div>{L("الفترة", "Period")}</div>
          <div>{L("الإجمالي", "Total")}</div><div>{L("الحالة", "Status")}</div><div>{L("الإصدار", "Issued")}</div><div>{L("إجراءات", "Actions")}</div>
        </div>
        {loading ? (
          <div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div>
        ) : rows.length === 0 ? (
          <div className="grid-empty">{L("لا فواتير مطابقة", "No matching invoices")}</div>
        ) : (
          rows.map((invoice, i) => {
            const meta = INVOICE_STATUS[invoice.status];
            const open = invoice.status === "due" || invoice.status === "overdue";
            return (
              <div key={invoice.id} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: COLS }}>
                <div><bdi>{invoice.number}</bdi></div>
                <div>
                  <Link href={`/sa/facilities/${invoice.facility_id}`} style={{ fontWeight: 700 }}>
                    {invoice.facility_name || L("فتح المنشأة", "Open facility")}
                  </Link>
                </div>
                <div><bdi style={{ fontSize: 12.5 }}>{invoice.period_start.slice(0, 10)} → {invoice.period_end.slice(0, 10)}</bdi></div>
                <div style={{ fontWeight: 700 }}><bdi>{fmtSar(invoice.total_sar)}</bdi></div>
                <div><span className={meta.cls}>{L(meta.ar, meta.en)}</span></div>
                <div style={{ fontSize: 12.5 }}>{fmtDateTime(invoice.issued_at)}</div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {open ? (
                    <>
                      <button className="btn-row" disabled={busy === invoice.id} onClick={() => void setInvoiceStatus(invoice, "paid")}>
                        {L("تسجيل سداد", "Mark paid")}
                      </button>
                      <button className="btn-row danger" disabled={busy === invoice.id} onClick={() => {
                        if (window.confirm(L(`إلغاء الفاتورة ${invoice.number}؟`, `Void invoice ${invoice.number}?`))) {
                          void setInvoiceStatus(invoice, "void");
                        }
                      }}>
                        {L("إلغاء", "Void")}
                      </button>
                    </>
                  ) : (
                    <span style={{ color: "#5B7280", fontSize: 12.5 }}>
                      {invoice.paid_at !== null ? fmtDateTime(invoice.paid_at) : "—"}
                    </span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      {pages > 1 ? (
        <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 14, alignItems: "center" }}>
          <button className="btn-secondary" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>
            {L("السابق", "Previous")}
          </button>
          <span style={{ fontSize: 13, color: "#5B7280" }}>
            <span className="num">{page}</span> / <span className="num">{pages}</span>
          </span>
          <button className="btn-secondary" disabled={page >= pages} onClick={() => setPage((value) => value + 1)}>
            {L("التالي", "Next")}
          </button>
        </div>
      ) : null}

      <p style={{ fontSize: 12.5, color: "#5B7280", margin: "10px 0 0" }}>
        {L("تسجيل السداد اليدوي يوثَّق بمرجع manual_* ويرفع تعليق المنشأة إن لم تبقَ متأخرات · الفواتير المسددة لا تُلغى (مسار الاسترداد خارج النطاق).",
           "Manual settlement is recorded with a manual_* reference and lifts facility suspension when no overdue remains · paid invoices cannot be voided (refunds are out of scope).")}
      </p>
    </>
  );
}

export default function SaInvoicesPage() {
  const { L } = useLang();
  return (
    <SaShell title={L("الفواتير والمدفوعات", "Invoices & payments")}>
      <main className="page-wrap">
        <Suspense>
          <InvoicesInner />
        </Suspense>
      </main>
    </SaShell>
  );
}
