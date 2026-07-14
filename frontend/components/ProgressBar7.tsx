"use client";

/** شريط التقدم الدائم بسبع مراحل — موتيف المنحنى الصاعد (DOC-11 §٣، حرفي من النموذج).
 *  current: 1..7 (المرحلة الحالية) · 8 = اكتمل الكل (رفع ناجح) · failStage: مرحلة فاشلة (7 عند فشل الرفع). */

const STAGES = ["المريض والقالب", "تسجيل", "تفريغ", "ملخص", "إرشاد", "تحرير واعتماد", "رفع"] as const;
const DASH = [0, 16.7, 33.3, 50, 66.7, 83.3, 100] as const;
const POS = [
  { left: 98.5, top: 78 }, { left: 83, top: 74 }, { left: 67, top: 67 }, { left: 50.2, top: 58 },
  { left: 33.5, top: 45 }, { left: 17, top: 29 }, { left: 1.5, top: 10 },
] as const;

export function ProgressBar7({ current, failStage }: { current: number; failStage?: number }) {
  const done = current >= 8;
  const dash = done ? 100 : DASH[Math.max(0, Math.min(6, current - 1))] ?? 0;
  return (
    <div style={{ background: "#fff", borderBottom: "1px solid #D7E3E8" }}>
      <div style={{ maxWidth: 960, margin: "0 auto", position: "relative", height: 128, padding: "0 10px" }}>
        <svg viewBox="0 0 1000 90" preserveAspectRatio="none"
          style={{ position: "absolute", top: 14, right: 0, left: 0, width: "100%", height: 90 }}>
          <path d="M985,78 C700,72 300,55 15,8" fill="none" stroke="#D7E3E8" strokeWidth="3" />
          <path d="M985,78 C700,72 300,55 15,8" fill="none" stroke="#2E9E5B" strokeWidth="3.5"
            pathLength={100} strokeDasharray={`${dash} 100`} strokeLinecap="round" />
        </svg>
        {STAGES.map((label, index) => {
          const stage = index + 1;
          const position = POS[index]!;
          const failed = failStage === stage;
          const completed = done || stage < current;
          const isCurrent = !done && stage === current && !failed;
          let border = "#D7E3E8"; let background = "#fff"; let color = "#5B7280"; let labelColor = "#5B7280";
          if (failed) { border = "#C0392B"; background = "#C0392B"; color = "#fff"; labelColor = "#C0392B"; }
          else if (completed) { border = "#2E9E5B"; background = "#2E9E5B"; color = "#fff"; labelColor = "#2E9E5B"; }
          else if (isCurrent) { border = "#0E7C86"; background = "#0E7C86"; color = "#fff"; labelColor = "#0A5C64"; }
          return (
            <div key={label} style={{
              position: "absolute", left: `${position.left}%`, top: position.top,
              transform: "translateX(-50%)", width: 104, textAlign: "center",
            }}>
              <div style={{
                width: 28, height: 28, borderRadius: 999, border: `2.5px solid ${border}`,
                background, color, display: "inline-flex", alignItems: "center", justifyContent: "center",
                fontSize: 12.5, fontWeight: 700,
                animation: isCurrent ? "mPulse 2.2s ease infinite" : undefined,
              }}>
                {completed && !failed ? "✓" : <span className="num">{stage}</span>}
              </div>
              <div style={{ fontSize: 12.5, fontWeight: isCurrent ? 700 : 400, color: labelColor, marginTop: 2 }}>{label}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
