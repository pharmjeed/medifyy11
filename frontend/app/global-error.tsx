"use client";

/** حاجز الأخطاء الجذري (يشمل أعطال layout) — نسخة W-004 مكتفية ذاتياً بلا اعتماد على CSS خارجي. */

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const arabic = typeof document !== "undefined" && document.documentElement.lang === "ar";
  const L = (ar: string, en: string) => (arabic ? ar : en);
  return (
    <html lang={arabic ? "ar" : "en"} dir={arabic ? "rtl" : "ltr"}>
      <body style={{ margin: 0, background: "#f7f9fb", color: "#0c1a36", fontFamily: '"Segoe UI",Tahoma,Arial,sans-serif', minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
        <div style={{ width: "min(470px,94vw)", background: "#fff", border: "1px solid #c7d1e0", borderRadius: 12, padding: 28, textAlign: "center" }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: "#d94b4b" }}>
            <bdi>MDF-5001</bdi>
          </div>
          <h1 style={{ fontSize: 18, fontWeight: 700, color: "#005a55", margin: "6px 0" }}>{L("حدث خطأ غير متوقع", "An unexpected error occurred")}</h1>
          <p style={{ fontSize: 14, color: "#5c7096", margin: "8px 0 16px" }}>
            {L("أعد المحاولة، وإن تكرر فحدّث الصفحة تحديثاً قسرياً", "Retry; if it persists, force-refresh the page")} (<bdi>Ctrl+Shift+R</bdi>).
          </p>
          <button
            onClick={() => reset()}
            style={{ height: 44, padding: "0 24px", border: "none", borderRadius: 10, background: "#00736d", color: "#fff", fontSize: 14, fontWeight: 700, cursor: "pointer", marginInlineEnd: 8 }}
          >{L("إعادة المحاولة", "Retry")}</button>
          <button
            onClick={() => window.location.reload()}
            style={{ height: 44, padding: "0 24px", border: "1.5px solid #00736d", borderRadius: 10, background: "#fff", color: "#005a55", fontSize: 14, fontWeight: 700, cursor: "pointer" }}
          >{L("تحديث الصفحة", "Refresh page")}</button>
        </div>
      </body>
    </html>
  );
}
