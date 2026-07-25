"use client";

/** منشآت المنصة — بحث وتصفية بالحالة، والصف يفتح صفحة إدارة المنشأة الكاملة. */

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { SaShell } from "@/components/SaShell";
import { Field, Modal, useToast } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { saApi } from "@/lib/sa";
import type { FacilityStatus, SaFacilityRow, SaPlan } from "@/lib/types";

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
  const [creating, setCreating] = useState(false);
  const [plans, setPlans] = useState<SaPlan[]>([]);

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

  // كتالوج دورات الفوترة — يملأ قائمة الباقة في نافذة الإنشاء
  useEffect(() => {
    void (async () => {
      try {
        setPlans((await saApi<SaPlan[]>("/plans")).data.filter((plan) => plan.is_active));
      } catch { /* الإنشاء يبقى ممكناً بالدورة الافتراضية */ }
    })();
  }, []);

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
        <button className="btn h40" onClick={() => setCreating(true)}>
          {L("+ منشأة جديدة", "+ New facility")}
        </button>
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
                <div className="num" style={{ color: row.overdue_count > 0 ? "#d94b4b" : "#5c7096", fontWeight: row.overdue_count > 0 ? 700 : 400 }}>
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
          <span style={{ fontSize: 13, color: "#5c7096" }}>
            <span className="num">{page}</span> / <span className="num">{pages}</span>
          </span>
          <button className="btn-secondary" disabled={page >= pages} onClick={() => setPage((value) => value + 1)}>
            {L("التالي", "Next")}
          </button>
        </div>
      ) : null}

      {creating ? (
        <NewFacilityModal
          plans={plans}
          onClose={() => setCreating(false)}
          onDone={(facilityId) => { setCreating(false); router.push(`/sa/facilities/${facilityId}`); }}
        />
      ) : null}
    </>
  );
}

/** إنشاء منشأة من المنصة — بيانات المنشأة وحساب أدمنها وعدد الدكاترة في نموذج واحد. */
function NewFacilityModal({ plans, onClose, onDone }: {
  plans: SaPlan[];
  onClose: () => void;
  onDone: (facilityId: string) => void;
}) {
  const toast = useToast();
  const { L, lang } = useLang();

  const [name, setName] = useState("");
  const [commercialReg, setCommercialReg] = useState("");
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [seats, setSeats] = useState(3);
  const [plan, setPlan] = useState("monthly");
  const [invoice, setInvoice] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = await saApi<{ id: string; admin_username: string }>("/facilities", {
        method: "POST",
        body: {
          name, commercial_reg: commercialReg, seats, plan,
          issue_first_invoice: invoice,
          admin: { full_name: fullName, username, email, password },
        },
      });
      toast(L(`أُنشئت ${name} — أدمنها ${body.data.admin_username}`,
              `${name} created — admin ${body.data.admin_username}`));
      onDone(body.data.id);
    } catch (err) {
      setError(err instanceof ApiError
        ? `${err.text(lang)} (${err.code})`
        : L("تعذر الاتصال بالخادم", "Could not reach the server"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={L("منشأة جديدة", "New facility")} onClose={onClose}>
      <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <Field label={L("اسم المنشأة", "Facility name")} value={name}
          onChange={(event) => setName(event.target.value)} required minLength={2} />
        <Field label={L("السجل التجاري", "Commercial registration")} ltr value={commercialReg}
          onChange={(event) => setCommercialReg(event.target.value)} required minLength={4} />

        <div className="sub-box" style={{ marginBottom: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 8 }}>
            {L("حساب أدمن المنشأة", "Facility admin account")}
          </div>
          <Field label={L("الاسم الكامل", "Full name")} value={fullName}
            onChange={(event) => setFullName(event.target.value)} required minLength={2} />
          <Field label={L("اسم المستخدم", "Username")} ltr value={username}
            onChange={(event) => setUsername(event.target.value)} required minLength={3} />
          <Field label={L("البريد (قناة الاستعادة — إلزامي)", "Email (recovery channel — required)")} ltr
            type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          <Field label={L("كلمة المرور", "Password")} ltr type="password" value={password}
            onChange={(event) => setPassword(event.target.value)} required minLength={8} />
        </div>

        <Field label={L("عدد الدكاترة", "Doctors count")} ltr type="number" min={1} max={500}
          value={String(seats)} onChange={(event) => setSeats(Number(event.target.value) || 1)} required />

        <label className="field-label">{L("دورة الفوترة", "Billing cycle")}</label>
        <select className="field" value={plan} onChange={(event) => setPlan(event.target.value)}>
          {plans.length === 0 ? <option value="monthly">monthly</option> : null}
          {plans.map((row) => (
            <option key={row.id} value={row.code}>
              {L(row.name_ar, row.name_en)} — {row.seat_price_sar} {L("ر.س/دكتور", "SAR/doctor")}
            </option>
          ))}
        </select>

        <label style={{ display: "flex", gap: 8, alignItems: "center", margin: "12px 0", fontSize: 13 }}>
          <input type="checkbox" checked={invoice} onChange={(event) => setInvoice(event.target.checked)} />
          {L("إصدار الفاتورة الأولى الآن", "Issue the first invoice now")}
        </label>
        <p style={{ fontSize: 12, color: "#5c7096", margin: "0 0 12px" }}>
          {L("اتركه مطفأً لحسابات العرض والتجريب — الإصدار من المنصة فعل صريح.",
             "Leave off for demo accounts — platform invoicing is an explicit action.")}
        </p>

        {error !== null ? <p style={{ color: "#d94b4b", fontSize: 12.5, fontWeight: 700, margin: "10px 0 0" }}>{error}</p> : null}
        <button className="btn" style={{ width: "100%" }} type="submit" disabled={busy}>
          {busy ? L("جارٍ الإنشاء…", "Creating…") : L("إنشاء المنشأة", "Create facility")}
        </button>
      </form>
    </Modal>
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
