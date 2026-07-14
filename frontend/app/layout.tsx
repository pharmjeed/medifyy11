import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@/styles/tokens.css";

export const metadata: Metadata = {
  title: "Medify — الكاتب الطبي الذكي",
  description: "منصة كاتب طبي ذكي محيطي ثنائية اللغة — عربي إلى SOAP مرمّز جاهز للرفع",
  icons: { icon: "/brand/medify-symbol.png" },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ar" dir="rtl">
      <body>{children}</body>
    </html>
  );
}
