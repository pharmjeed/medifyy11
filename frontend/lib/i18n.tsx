"use client";

/** i18n خفيف بلا مكتبات: أزواج نصية في مكانها L(ar, en) + سياق لغة يقلب اتجاه الصفحة.
 *  الافتراضي إنجليزي (قرار مالك 2026-07-15 — D-30)؛ الاختيار محفوظ في localStorage. */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

export type Lang = "en" | "ar";

const LANG_KEY = "medify_lang";
export const DEFAULT_LANG: Lang = "en";

export function readStoredLang(): Lang {
  if (typeof window === "undefined") return DEFAULT_LANG;
  try {
    const stored = window.localStorage.getItem(LANG_KEY);
    return stored === "ar" || stored === "en" ? stored : DEFAULT_LANG;
  } catch {
    return DEFAULT_LANG;
  }
}

function applyLangToDocument(lang: Lang): void {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
}

interface LangContextValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  /** يختار النص حسب اللغة الحالية — الاستخدام: L("العيادات", "Clinics") */
  L: (ar: string, en: string) => string;
}

const LangContext = createContext<LangContextValue>({
  lang: DEFAULT_LANG,
  setLang: () => undefined,
  L: (ar, en) => ((DEFAULT_LANG as Lang) === "ar" ? ar : en),
});

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(DEFAULT_LANG);

  useEffect(() => {
    const stored = readStoredLang();
    setLangState(stored);
    applyLangToDocument(stored);
  }, []);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    applyLangToDocument(next);
    try {
      window.localStorage.setItem(LANG_KEY, next);
    } catch {
      /* جلسة بلا تخزين */
    }
  }, []);

  const L = useCallback((ar: string, en: string) => (lang === "ar" ? ar : en), [lang]);

  return <LangContext.Provider value={{ lang, setLang, L }}>{children}</LangContext.Provider>;
}

export function useLang(): LangContextValue {
  return useContext(LangContext);
}

/** زر تبديل اللغة — يظهر في الشريط العلوي وصفحتي الدخول/التسجيل. */
export function LangToggle({ floating }: { floating?: boolean }) {
  const { lang, setLang } = useLang();
  return (
    <button
      onClick={() => setLang(lang === "ar" ? "en" : "ar")}
      aria-label={lang === "ar" ? "Switch to English" : "التبديل إلى العربية"}
      title={lang === "ar" ? "English" : "العربية"}
      style={{
        height: 40, minWidth: 52, padding: "0 12px", border: "1px solid #D7E3E8", borderRadius: 10,
        background: "#fff", color: "#0A5C64", fontSize: 12.5, fontWeight: 700, cursor: "pointer",
        display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6,
        ...(floating === true ? { position: "fixed", top: 14, insetInlineEnd: 14, zIndex: 45 } : {}),
      }}
    >
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#0A5C64" strokeWidth="2" strokeLinecap="round">
        <circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" />
        <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
      </svg>
      {lang === "ar" ? <bdi className="ui">EN</bdi> : "عربي"}
    </button>
  );
}

/** سكربت يطبق اللغة المحفوظة قبل الرسم الأول — يُحقن في layout لمنع وميض الاتجاه. */
export const LANG_BOOT_SCRIPT = `(function(){try{var l=localStorage.getItem("${LANG_KEY}");l=(l==="ar"||l==="en")?l:"${DEFAULT_LANG}";document.documentElement.lang=l;document.documentElement.dir=l==="ar"?"rtl":"ltr";}catch(e){}})();`;
