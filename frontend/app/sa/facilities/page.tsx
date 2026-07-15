"use client";

/** منشآت المنصة — بحث وتصفية بالحالة، والصف يفتح صفحة إدارة المنشأة الكاملة. */

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { SaShell } from "@/components/SaShell";
import { useToast } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { saApi } from "@/lib/sa";
import type { FacilityStatus, SaFacilityRow } from "@/lib/types";

const COLS = "1.6fr 1fr .8fr .7fr .7fr .7fr .8fr";

const FACILITY_STATUS_META: Record<FacilityStatus, { ar: string; en: string; cls: string }> = {
  active: { ar: "نشطة", en: "Active", cls: "badge success" },
  suspended: { ar: "معلّقة", en: "Suspended", cls: "badge warn" },
  archived: { ar: "مؤرشفة", en: "Archived", cls: "badge neutral" },
};

function FacilitiesInner() {
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();
  const { L, lang } = useLang();

  const [rows, setRows] = useState<SaFacilityRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState(params.get("status") ?? "");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (searchQ: string, searchStatus: string, searchPage: number) => {
    setLoading(true);
    try {
      const query = new URLSearchParams({ page: String(searchPage), per_page: "25" });
      if (searchQ) query.set("q", searchQ);
      if (searchStatus) query.set("status", searchStatus);
      const body = await saApi<SaFacilityRow[]>(`/facilities?${query.toString()}`);
      setRows(body.data);
      setTotal(body.meta.total ?? 0);
    } catch (err) {
      toast(err instanceof ApiError ? `${err.text(lang)} (${err.code})` : L("تعذر الاتصال بالخادم", "Could not reach the server"));
    } finally {
      setLoading(false);
    }
  }, [toast, lang, L]);

  useEffect(() => { void load(q, status, page); }, [load, status, page]); // eslint-disable-line react-hooks/exhaustive-deps

  const pages = Math.max(1, Math.ceil(total / 25));

  return (
    <>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
        <form style={{ flex: 1, minWidth: 220, display: "flex", gap: 8 }}
          onSubmit={(event) => { event.preventDefault(); setPage(1); void load(q, status, 1); }}>
          <input className="field" style={{ margin: 0, flex: 1 }} value={q}
            placeholder={L("بحث بالاسم أو السجل التجاري…", "Search by name or commercial registration…")}
            onChange={(event) => setQ(event.target.value)} />
          <button type="submit" className="btn h40">{L("بحث", "Search")}</button>
        </form>
        <div className="tabs" role="tablist" style={{ margin: 0 }}>
          {[["", L("الكل", "All")], ["active", L("نشطة", "Active")], ["suspended", L("معلّقة", "Suspended")], ["archived", L("مؤرشفة", "Archived")]].map(([key, label]) => (
            <button key={key} role="tab" aria-selected={status === key}
              className={status === key ? "tab active" : "tab"}
              onClick={() => { setStatus(key ?? ""); setPage(1); }}>{label}</button>
          ))}
        </div>
      </div>

      <div className="grid-table">
        <div className="grid-head" style={{ gridTemplateColumns: COLS }}>
          <div>{L("المنشأة", "Facility")}</div>
          <div>{L("السجل التجاري", "Comm. reg.")}</div>
          <div>{L("الباقة", "Plan")}</div>
          <div>{L("المقاعد", "Seats")}</div>
          <div>{L("دكاترة نشطون", "Active drs")}</div>
          <div>{L("متأخرات", "Overdue")}</div>
          <div>{L("الحالة", "Status")}</div>
        </div>
        {loading ? (
          <div className="grid-empty">{L("جارٍ التحميل…", "Loading…")}</div>
        ) : rows.length === 0 ? (
          <div className="grid-empty">{L("لا منشآت مطابقة", "No matching facilities")}</div>
        ) : (
          rows.map((row, i) => {
            const meta = FACILITY_STATUS_META[row.status];
            return (
              <div key={row.id} className={i % 2 ? "grid-row odd" : "grid-row"}
                style={{ gridTemplateColumns: COLS, cursor: "pointer" }}
                onClick={() => router.push(`/sa/facilities/${row.id}`)}>
                <div style={{ fontWeight: 700 }}>{row.name}</div>
                <div><bdi className="num">{row.commercial_reg}</bdi></div>
                <div><bdi>{row.plan ?? "—"}</bdi></div>
                <div className="num">{row.seats_total}</div>
                <div className="num">{row.doctors_active}</div>
                <div className="num" style={{ color: row.overdue_count > 0 ? "#C0392B" : "#5B7280", fontWeight: row.overdue_count > 0 ? 700 : 400 }}>
                  {row.overdue_count}
                </div>
                <div><span className={meta.cls}>{L(meta.ar, meta.en)}</span></div>
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
    </>
  );
}

export default function SaFacilitiesPage() {
  const { L } = useLang();
  return (
    <SaShell title={L("المنشآت", "Facilities")}>
      <main className="page-wrap">
        <Suspense>
          <FacilitiesInner />
        </Suspense>
      </main>
    </SaShell>
  );
}
