"use client";

/** الصفحة 10 — سجل التدقيق W-110: فلتر حدث + ترقيم صفحي (FR-303 · NFR-10). */

import { useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { SpecBar, fmtDateTime, useToast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import type { AuditRow } from "@/lib/types";

const PER_PAGE = 25;
const AUDIT_COLS = "1.1fr 1.2fr 1.9fr 1fr .8fr";

function AuditInner() {
  const toast = useToast();
  const { L, lang } = useLang();
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
      toast(err instanceof ApiError ? `${err.text(lang)} (${err.code})` : L("تعذر الاتصال بالخادم", "Could not reach the server"));
    } finally {
      setLoading(false);
    }
  }, [action, page, toast, lang, L]);

  useEffect(() => { void load(); }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));

  return (
    <>
      <SpecBar ids="W-110" desc={L("الصفحة 10 — سجل التدقيق (FR-303 · NFR-10)", "Page 10 — Audit log (FR-303 · NFR-10)")} />

      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 14 }}>
        <h1 className="page-title" style={{ margin: 0 }}>{L("سجل التدقيق", "Audit log")}</h1>
        <span className="badge" style={{ background: "#EAF6F7", color: "#0A5C64" }}>
          {L("إلحاقي فقط — لا تعديل ولا حذف", "Append-only — no edits, no deletions")}
        </span>
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
            placeholder={L("بحث في العمليات… (مثال: invoice)", "Search actions… (e.g. invoice)")}
            aria-label={L("بحث في العمليات", "Search actions")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <button type="submit" className="btn h40">{L("بحث", "Search")}</button>
        </form>
      </div>

      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: AUDIT_COLS }}>
          <div>{L("الوقت", "Time")}</div><div>{L("المنفّذ", "Actor")}</div><div>{L("الحدث", "Action")}</div><div>{L("الكيان", "Entity")}</div><div>{L("معرف الكيان", "Entity ID")}</div>
        </div>
        {loading ? (
          <div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div>
        ) : rows.length === 0 ? (
          <div className="grid-empty">{L("لا نتائج مطابقة", "No matching results")}</div>
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
        >{L("السابق", "Previous")}</button>
        <span style={{ fontSize: 12.5, color: "#5B7280" }}>
          {L("صفحة", "Page")} <span className="num">{page}</span> {L("من", "of")} <span className="num">{totalPages}</span>
        </span>
        <button
          className="btn-secondary"
          style={{ height: 36, padding: "0 16px", fontSize: 12.5 }}
          disabled={page >= totalPages || loading}
          onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
        >{L("التالي", "Next")}</button>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 12.5, color: "#5B7280" }}>
          {L("عدد السجلات:", "Total records:")} <span className="num">{total}</span>
        </span>
      </div>

      <p style={{ fontSize: 12.5, color: "#5B7280", margin: "14px 0 0" }}>
        {L("سجل إلحاقي غير قابل للتعديل (NFR-10) — إدخاله آلي من النظام",
           "Append-only, immutable log (NFR-10) — entries are written automatically by the system")}
      </p>
    </>
  );
}

export default function AuditPage() {
  const { L } = useLang();
  return (
    <Shell title={L("سجل التدقيق", "Audit log")}>
      <main className="page-wrap">
        <AuditInner />
      </main>
    </Shell>
  );
}
