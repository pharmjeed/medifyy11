"use client";

/** حاجز أخطاء المسارات — يعرض بنمط W-004 (رمز MDF + إجراء مقترح) بدل رسالة Next الخام. */

export default function RouteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const arabic = typeof document !== "undefined" && document.documentElement.lang === "ar";
  const L = (ar: string, en: string) => (arabic ? ar : en);
  return (
    <main style={{ minHeight: "60vh", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <div style={{ width: "min(470px,94vw)", background: "#fff", border: "1px solid #D7E3E8", borderRadius: 12, padding: 28, textAlign: "center" }}>
        <div style={{ width: 56, height: 56, borderRadius: 999, background: "#FDEEEE", display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#C0392B" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4" /><path d="M12 17h.01" />
          </svg>
        </div>
        <div style={{ marginTop: 10 }}>
          <bdi style={{ fontSize: 22, fontWeight: 700, color: "#C0392B", fontFamily: "var(--m-mono)" }}>MDF-5001</bdi>
        </div>
        <h1 style={{ fontSize: 18, fontWeight: 700, color: "#0A5C64", margin: "6px 0" }}>{L("حدث خطأ غير متوقع", "An unexpected error occurred")}</h1>
        <p style={{ fontSize: 14, color: "#5B7280", margin: "8px 0 4px" }}>
          {L("خطأ في واجهة المتصفح — غالباً بسبب نسخة قديمة محفوظة بعد تحديث للمنصة.",
             "A browser-side error — usually a stale cached version after a platform update.")}
        </p>
        <p style={{ fontSize: 12.5, color: "#5B7280", margin: "0 0 16px" }}>
          {L("أعد المحاولة، وإن تكرر فحدّث الصفحة تحديثاً قسرياً", "Retry; if it persists, force-refresh the page")} (<bdi>Ctrl+Shift+R</bdi>).
        </p>
        {error.digest !== undefined ? (
          <p style={{ marginBottom: 14 }}><span className="tech-badge">trace_{error.digest}</span></p>
        ) : null}
        <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
          <button className="btn" onClick={() => reset()}>{L("إعادة المحاولة", "Retry")}</button>
          <button className="btn-secondary" onClick={() => window.location.reload()}>{L("تحديث الصفحة", "Refresh page")}</button>
        </div>
      </div>
    </main>
  );
}
