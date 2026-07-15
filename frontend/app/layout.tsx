import type { Metadata } from "next";
import type { ReactNode } from "react";
import { LANG_BOOT_SCRIPT, LangProvider } from "@/lib/i18n";
import "@/styles/tokens.css";

export const metadata: Metadata = {
  title: "Medify — Ambient AI Medical Scribe",
  description: "منصة كاتب طبي ذكي محيطي ثنائية اللغة — Arabic consultations to coded SOAP, ready for hospital upload",
  icons: { icon: "/brand/medify-symbol.png" },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  // اللغة الافتراضية إنجليزية (D-30)؛ السكربت يطبق المحفوظة قبل الرسم لمنع وميض الاتجاه
  return (
    <html lang="en" dir="ltr" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: LANG_BOOT_SCRIPT }} />
      </head>
      <body>
        <LangProvider>{children}</LangProvider>
      </body>
    </html>
  );
}
