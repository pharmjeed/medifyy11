"use client";

/** الصفحة 10 — سجل التدقيق W-110: فلتر حدث + ترقيم صفحي (FR-303 · NFR-10). */

import { useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { SpecBar, fmtDateTime, useToast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { AuditRow } from "@/lib/types";

const PER_PAGE = 25;
const AUDIT_COLS = "1.1fr 1.2fr 1.9fr 1fr .8fr";

function apiErrorText(err: unknown): string {
  return err instanceof ApiError ? `${err.messageAr} (${err.code})` : "تعذر الاتصال بالخادم";
}

function AuditInner() {
  const toast = useToast();
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [action, setAction] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const filter = action.trim() === "" ? "" : `&action=${encodeURIComponent(action.trim())}`;
      const body = await api<AuditRow[]>(`/audit-logs?page=${page}&per_page=${PER_PAGE}${filter}`);
      setRows(body.data);
      setTotal(body.meta.total ?? 0);
    } catch (err) {
      toast(apiErrorText(err));
    } finally {
      setLoading(false);
    }
  }, [action, page, toast]);

  useEffect(() => { void load(); }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));

  return (
    <>
      <SpecBar ids="W-110" desc="الصفحة 10 — سجل التدقيق (FR-303 · NFR-10)" />

      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 14 }}>
        <h1 className="page-title" style={{ margin: 0 }}>سجل التدقيق</h1>
        <span className="badge" style={{ background: "#EAF6F7", color: "#0A5C64" }}>إلحاقي فقط — لا تعديل ولا حذف</span>
        <span style={{ flex: 1 }} />
        <form
          style={{ display: "flex", gap: 8, alignItems: "center" }}
          onSubmit={(event) => {
            event.preventDefault();
            setPage(1);
            setAction(query);
          }}
        >
          <input
            className="field"
            style={{ width: "min(300px, 100%)" }}
            placeholder="بحث في العمليات… (مثال: invoice)"
            aria-label="بحث في العمليات"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <button type="submit" className="btn h40">بحث</button>
        </form>
      </div>

      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: AUDIT_COLS }}>
          <div>الوقت</div><div>المنفّذ</div><div>الحدث</div><div>الكيان</div><div>معرف الكيان</div>
        </div>
        {loading ? (
          <div className="grid-empty">جارٍ التحميل…</div>
        ) : rows.length === 0 ? (
          <div className="grid-empty">لا نتائج مطابقة</div>
        ) : (
          rows.map((row, i) => (
            <div key={row.id} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: AUDIT_COLS }}>
              <div>{fmtDateTime(row.at)}</div>
              <div>{row.actor}</div>
              <div><span className="tech-badge">{row.action}</span></div>
              <div><bdi>{row.entity}</bdi></div>
              <div>
                {row.entity_id !== null && row.entity_id !== "" ? (
                  <bdi title={row.entity_id}>{row.entity_id.slice(0, 8)}</bdi>
                ) : (
                  <span style={{ color: "#5B7280" }}>—</span>
                )}
              </div>
            </div>
          ))
        )}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 14, flexWrap: "wrap" }}>
        <button
          className="btn-secondary"
          style={{ height: 36, padding: "0 16px", fontSize: 12.5 }}
          disabled={page <= 1 || loading}
          onClick={() => setPage((value) => Math.max(1, value - 1))}
        >السابق</button>
        <span style={{ fontSize: 12.5, color: "#5B7280" }}>
          صفحة <span className="num">{page}</span> من <span className="num">{totalPages}</span>
        </span>
        <button
          className="btn-secondary"
          style={{ height: 36, padding: "0 16px", fontSize: 12.5 }}
          disabled={page >= totalPages || loading}
          onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
        >التالي</button>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 12.5, color: "#5B7280" }}>
          عدد السجلات: <span className="num">{total}</span>
        </span>
      </div>

      <p style={{ fontSize: 12.5, color: "#5B7280", margin: "14px 0 0" }}>
        سجل إلحاقي غير قابل للتعديل (NFR-10) — إدخاله آلي من النظام
      </p>
    </>
  );
}

export default function AuditPage() {
  return (
    <Shell title="سجل التدقيق">
      <main className="page-wrap">
        <AuditInner />
      </main>
    </Shell>
  );
}
