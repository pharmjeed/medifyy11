"use client";

/** مميزات باقة المنشأة (قرار مالك 2026-08-03) — ما تُظهره الواجهة للدكتور.
 *
 *  الإخفاء هنا تجربة استخدام فقط، تماماً كحارس الدور في Shell: المنع الفعلي على الخادم
 *  (`require_feature` → MDF-4032) فلا يفتح شيئاً تعديلُ حالة في المتصفح.
 *
 *  الترطيب متزامن من localStorage (آخر خريطة معروفة) كي لا يومض زر ثم يختفي، ثم تحديث
 *  خلفي من /features عند كل تحميل — فتغيير المالك يظهر للدكتور في أول تنقّل بلا إعادة دخول. */

import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "./api";
import type { FeatureCatalogItem, FeatureMap } from "./types";

const FEATURES_KEY = "medify_features";

/** الافتراض قبل وصول الرد: كل شيء مفتوح — الخادم هو من يمنع، والواجهة لا تُخفي بالظن. */
const ALL_ON = new Proxy({} as FeatureMap, { get: () => true });

interface FeaturesValue {
  features: FeatureMap;
  catalog: FeatureCatalogItem[];
  planCode: string | null;
  loaded: boolean;
}

const FeaturesContext = createContext<FeaturesValue>({
  features: ALL_ON,
  catalog: [],
  planCode: null,
  loaded: false,
});

function readStored(): FeatureMap | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(FEATURES_KEY);
    return raw === null ? null : (JSON.parse(raw) as FeatureMap);
  } catch {
    return null;
  }
}

export function clearStoredFeatures(): void {
  try {
    window.localStorage.removeItem(FEATURES_KEY);
  } catch {
    /* تجاهل */
  }
}

interface FeaturesResponse {
  plan: { code: string; name_ar: string; name_en: string } | null;
  features: FeatureMap;
  catalog: FeatureCatalogItem[];
}

export function FeaturesProvider({ children }: { children: ReactNode }) {
  const [value, setValue] = useState<FeaturesValue>(() => {
    const stored = readStored();
    return { features: stored ?? ALL_ON, catalog: [], planCode: null, loaded: stored !== null };
  });

  useEffect(() => {
    void (async () => {
      try {
        const body = await api<FeaturesResponse>("/features");
        setValue({
          features: body.data.features,
          catalog: body.data.catalog,
          planCode: body.data.plan?.code ?? null,
          loaded: true,
        });
        try {
          window.localStorage.setItem(FEATURES_KEY, JSON.stringify(body.data.features));
        } catch {
          /* جلسة بلا تخزين — يُعاد الجلب في كل صفحة */
        }
      } catch {
        /* تعذّر الجلب: نبقى على آخر خريطة معروفة (أو المفتوح) — الخادم يحرس فعلياً */
      }
    })();
  }, []);

  return <FeaturesContext.Provider value={value}>{children}</FeaturesContext.Provider>;
}

export function useFeatures(): FeaturesValue {
  return useContext(FeaturesContext);
}

/** الاستخدام: `const canHearVisit = useFeature("visit.audio_playback")` */
export function useFeature(key: string): boolean {
  const { features } = useFeatures();
  return features[key] !== false;
}
