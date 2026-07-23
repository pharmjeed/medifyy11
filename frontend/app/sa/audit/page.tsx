"use client";

/** W-SA-09 — سجل تدقيق المنصة الموحّد: كل أفعال السوبر أدمن عبر المنشآت (إلحاقي — لا حذف). */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { SaShell } from "@/components/SaShell";
import { fmtDateTime, useToast } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { saApi } from "@/lib/sa";

interface AuditRow {
  id: string;
  at: string;
  actor: string;
  actor_role: string;
  action: string;
  facility_id: string | null;
  facility_name: string | null;
  entity: string;
  entity_id: string | null;
  ip: string | null;
  meta: Record<string, unknown> | null;
}

const COLS = "1fr .9fr 1.4fr 1.2fr .9fr 1.6fr";

function AuditInner() {
  const toast = useToast();
  const { L, lang } = useLang();
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [actionFilter, setActionFilter] = useState("");
  const [actorFilter, setActorFilter] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (action: string, actor: string, searchPage: number) => {
    setLoading(true);
    try {
      const query = new URLSearchParams({ page: String(searchPage), per_page: "50" });
      if (action) query.set("action", action);
      if (actor) query.set("actor", actor);
      const body = await saApi<AuditRow[]>(`/audit?${query.toString()}`);
      setRows(body.data);
      setTotal(body.meta.total ?? 0);
    } catch (err) {
      toast(err instanceof ApiError ? `${err.text(lang)} (${err.code})` : L("تعذر الاتصال بالخادم", "Could not reach the server"));
    } finally {
      setLoading(false);
    }
  }, [toast, lang, L]);

  useEffect(() => { void load(actionFilter, actorFilter, page); }, [load, page]); // eslint-disable-line react-hooks/exhaustive-deps

  const pages = Math.max(1, Math.ceil(total / 50));

  return (
    <>
      <form style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}
        onSubmit={(event) => { event.preventDefault(); setPage(1); void load(actionFilter, actorFilter, 1); }}>
        <input className="field" style={{ margin: 0, flex: 1, minWidth: 180 }} value={actionFilter}
          placeholder={L("تصفية بالفعل (مثل sa.invoice)…", "Filter by action (e.g. sa.invoice)…")}
          onChange={(event) => setActionFilter(event.target.value)} />
        <input className="field" style={{ margin: 0, flex: 1, minWidth: 140 }} value={actorFilter}
          placeholder={L("تصفية بالفاعل…", "Filter by actor…")}
          onChange={(event) => setActorFilter(event.target.value)} />
        <button type="submit" className="btn h40">{L("تصفية", "Filter")}</button>
        <span style={{ alignSelf: "center", fontSize: 13, color: "#5c7096" }}>
          {L("الإجمالي:", "Total:")} <span className="num">{total}</span>
        </span>
      </form>

      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: COLS }}>
          <div>{L("الوقت", "Time")}</div><div>{L("الفاعل", "Actor")}</div><div>{L("الفعل", "Action")}</div>
          <div>{L("المنشأة", "Facility")}</div><div>{L("الكيان", "Entity")}</div><div>{L("التفاصيل", "Details")}</div>
        </div>
        {loading ? (
          <div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div>
        ) : rows.length === 0 ? (
          <div className="grid-empty">{L("لا سجلات مطابقة", "No matching records")}</div>
        ) : (
          rows.map((row, i) => (
            <div key={row.id} className={i % 2 ? "grid-row odd" : "grid-row"} style={{ gridTemplateColumns: COLS }}>
              <div style={{ fontSize: 12.5 }}>{fmtDateTime(row.at)}</div>
              <div>
                <span style={{ fontWeight: 700 }}>{row.actor}</span>
                <span className="tech-badge" style={{ marginInlineStart: 4 }}>{row.actor_role}</span>
              </div>
              <div><bdi style={{ fontSize: 12.5, fontWeight: 700 }}>{row.action}</bdi></div>
              <div style={{ fontSize: 12.5 }}>
                {row.facility_id !== null ? (
                  <Link href={`/sa/facilities/${row.facility_id}`}>{row.facility_name ?? L("فتح", "Open")}</Link>
                ) : (
                  <span style={{ color: "#5c7096" }}>{L("المنصة", "Platform")}</span>
                )}
              </div>
              <div><bdi style={{ fontSize: 12 }}>{row.entity}</bdi></div>
              <div style={{ fontSize: 11.5, color: "#5c7096", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                <bdi title={row.meta ? JSON.stringify(row.meta) : ""}>
                  {row.meta ? JSON.stringify(row.meta) : "—"}
                </bdi>
              </div>
            </div>
          ))
        )}
      </div>

      {pages > 1 ? (
        <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 14, alignItems: "center" }}>
          <button className="btn-secondary" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>
            {L("السابق", "Previous")}
          </button>
          <span style={{ fontSize: 13, color: "#5c7096" }}>
            <span className="num">{page}</span> / <span className="num">{pages}</span>
          </span>
          <button className="btn-secondary" disabled={page >= pages} onClick={() => setPage((value) => value + 1)}>
            {L("التالي", "Next")}
          </button>
        </div>
      ) : null}

      <p style={{ fontSize: 12.5, color: "#5c7096", margin: "10px 0 0" }}>
        {L("السجل إلحاقي — لا تعديل ولا حذف حتى للمالك · تدوين مزدوج: هنا وفي سجل تدقيق المنشأة المعنية.",
           "Append-only — no edits or deletions even for the owner · dual-recorded here and in the target facility's audit log.")}
      </p>
    </>
  );
}

export default function SaAuditPage() {
  const { L } = useLang();
  return (
    <SaShell title={L("سجل المنصة", "Platform audit")}>
      <main className="page-wrap">
        <AuditInner />
      </main>
    </SaShell>
  );
}
