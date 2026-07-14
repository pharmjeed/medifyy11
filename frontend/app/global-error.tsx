"use client";

/** حاجز الأخطاء الجذري (يشمل أعطال layout) — نسخة W-004 مكتفية ذاتياً بلا اعتماد على CSS خارجي. */

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="ar" dir="rtl">
      <body style={{ margin: 0, background: "#F7FAFB", color: "#0F2233", fontFamily: '"Segoe UI",Tahoma,Arial,sans-serif', minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
        <div style={{ width: "min(470px,94vw)", background: "#fff", border: "1px solid #D7E3E8", borderRadius: 12, padding: 28, textAlign: "center" }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: "#C0392B" }}>
            <bdi>MDF-5001</bdi>
          </div>
          <h1 style={{ fontSize: 18, fontWeight: 700, color: "#0A5C64", margin: "6px 0" }}>حدث خطأ غير متوقع</h1>
          <p style={{ fontSize: 14, color: "#5B7280", margin: "8px 0 16px" }}>
            أعد المحاولة، وإن تكرر فحدّث الصفحة تحديثاً قسرياً (<bdi>Ctrl+Shift+R</bdi>).
          </p>
          <button
            onClick={() => reset()}
            style={{ height: 44, padding: "0 24px", border: "none", borderRadius: 10, background: "#0E7C86", color: "#fff", fontSize: 14, fontWeight: 700, cursor: "pointer", marginInlineEnd: 8 }}
          >إعادة المحاولة</button>
          <button
            onClick={() => window.location.reload()}
            style={{ height: 44, padding: "0 24px", border: "1.5px solid #0E7C86", borderRadius: 10, background: "#fff", color: "#0A5C64", fontSize: 14, fontWeight: 700, cursor: "pointer" }}
          >تحديث الصفحة</button>
        </div>
      </body>
    </html>
  );
}
