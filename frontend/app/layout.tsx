import type { Metadata } from "next";
import type { ReactNode } from "react";
import { LANG_BOOT_SCRIPT, LangProvider } from "@/lib/i18n";
import "@/styles/tokens.css";

export const metadata: Metadata = {
  title: "Medify — التوثيق الطبي الذكي للرعاية الصحية السعودية",
  description: "منصة كاتب طبي ذكي تحول الاستشارة العربية إلى ملاحظة SOAP مهيكلة ومرمّزة، جاهزة للمراجعة والاعتماد والرفع إلى نظام المستشفى.",
  icons: { icon: "/brand/medify-symbol.png" },
  openGraph: {
    title: "Medify — أنصت لمريضك. اترك التوثيق لنا.",
    description: "من الاستشارة العربية إلى SOAP مرمّز وجاهز للرفع، مع اعتماد الطبيب قبل خروج البيانات.",
    type: "website",
    locale: "ar_SA",
  },
  twitter: {
    card: "summary_large_image",
    title: "Medify — التوثيق الطبي الذكي",
    description: "كاتب طبي ذكي صُمم للرعاية الصحية السعودية.",
  },
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
