"use client";

/** «بانتظارك» (م16 من التحصين) — أربع مجموعات بعمر كل بند، الأقدم أولاً،
 *  والنقر يفتح الزيارة على المرحلة الصحيحة. المُبطلة لا تظهر. */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { Shell } from "@/components/Shell";
import { useErrorScreen } from "@/components/ui";

interface PendingRow {
  visit_id: string;
  patient_name: string;
  patient_mrn: string;
  entered_review_at: string;
  age_hours: number;
  pending_guidance_count: number;
  version: number;
}

interface PendingQueue {
  total: number;
  counts: Record<string, number>;
  groups: Record<string, PendingRow[]>;
  as_of: string;
}

const GROUP_META: { key: string; ar: string; en: string; desc: { ar: string; en: string } }[] = [
  {
    key: "reopened_not_uploaded", ar: "أُعيد فتحها ولم تُنقل", en: "Reopened, not transferred",
    desc: { ar: "نسخة جديدة قيد الإعداد — تلزمها البوابتان ثم النقل",
            en: "A new version in progress — both gates then transfer are required" },
  },
  {
    key: "awaiting_gate_two", ar: "بانتظار البوابة ②", en: "Awaiting gate ②",
    desc: { ar: "النص معتمد — يبقى حسم الأكواد والاعتماد النهائي",
            en: "Note approved — codes resolution and final approval remain" },
  },
  {
    key: "pending_guidance", ar: "إرشادات معلّقة", en: "Pending guidance",
    desc: { ar: "بنود إرشاد تنتظر قرارك قبل اعتماد الأكواد",
            en: "Guidance items awaiting your decision before code approval" },
  },
  {
    key: "in_review", ar: "قيد المراجعة", en: "In review",
    desc: { ar: "دخلت المراجعة ولم يُحسم فيها شيء بعد",
            en: "Entered review with nothing resolved yet" },
  },
];

function ageLabel(hours: number, L: (ar: string, en: string) => string): string {
  if (hours < 1) return L("أقل من ساعة", "under an hour");
  if (hours < 24) return L(`${Math.round(hours)} ساعة`, `${Math.round(hours)}h`);
  const days = Math.floor(hours / 24);
  return L(`${days} يوم`, `${days}d`);
}

export default function PendingPage() {
  const router = useRouter();
  const { L } = useLang();
  const showError = useErrorScreen();
  const [queue, setQueue] = useState<PendingQueue | null>(null);

  const load = useCallback(async () => {
    try {
      const body = await api<PendingQueue>("/physicians/me/pending");
      setQueue(body.data);
    } catch (err) {
      showError(err);
    }
  }, [showError]);

  useEffect(() => { void load(); }, [load]);

  return (
    <Shell title={L("بانتظارك", "Awaiting you")}>
      <main className="page-wrap">
        <h1 className="page-title">{L("بانتظارك", "Awaiting you")}</h1>
        <p className="page-desc">
          {L("كل زيارة دخلت المراجعة ولم تكتمل — مرتّبة بالأقدم أولاً داخل كل مجموعة. النقر يفتح الزيارة على مرحلتها.",
             "Every visit that entered review and is not complete — oldest first within each group. Clicking opens the visit at its stage.")}
        </p>

        {queue === null ? (
          <div className="card"><span className="spinner dark" /></div>
        ) : queue.total === 0 ? (
          <div className="card pad24" style={{ textAlign: "center" }}>
            <div style={{ fontSize: 34 }}>✓</div>
            <strong style={{ fontSize: 17 }}>{L("لا شيء بانتظارك", "Nothing is awaiting you")}</strong>
            <p style={{ fontSize: 13, color: "#5c7096" }}>
              {L("كل زياراتك مكتملة — لن يصلك تذكير يومي ما دام الطابور فارغاً.",
                 "All your visits are complete — no daily reminder is sent while the queue is empty.")}
            </p>
          </div>
        ) : (
          GROUP_META.map((group) => {
            const rows = queue.groups[group.key] ?? [];
            if (rows.length === 0) return null;
            return (
              <section key={group.key} className="card" style={{ marginTop: 14 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <strong style={{ fontSize: 15.5 }}>{L(group.ar, group.en)}</strong>
                  <span className="badge info"><span className="num">{rows.length}</span></span>
                  <span style={{ fontSize: 12.5, color: "#5c7096", flex: 1 }}>{L(group.desc.ar, group.desc.en)}</span>
                </div>
                <div style={{ marginTop: 8 }}>
                  {rows.map((row) => (
                    <button key={row.visit_id} className="btn-row"
                      style={{ display: "flex", width: "100%", alignItems: "center", gap: 10,
                               justifyContent: "flex-start", marginBottom: 6, textAlign: "start" }}
                      onClick={() => router.push(`/doctor/visits/${row.visit_id}/review`)}>
                      <span style={{ flex: 1 }}>
                        {row.patient_name} <bdi className="tech-badge">{row.patient_mrn}</bdi>
                        {row.version > 1 ? (
                          <span className="badge info" style={{ marginInlineStart: 6 }}>
                            {L(`نسخة ${row.version}`, `v${row.version}`)}
                          </span>
                        ) : null}
                        {row.pending_guidance_count > 0 ? (
                          <span className="badge warn" style={{ marginInlineStart: 6 }}>
                            {L(`${row.pending_guidance_count} معلّق`, `${row.pending_guidance_count} pending`)}
                          </span>
                        ) : null}
                      </span>
                      <span style={{ fontSize: 12.5, color: row.age_hours >= 24 ? "var(--m-danger)" : "#5c7096" }}>
                        {L("منذ", "for")} {ageLabel(row.age_hours, L)}
                      </span>
                    </button>
                  ))}
                </div>
              </section>
            );
          })
        )}
      </main>
    </Shell>
  );
}
