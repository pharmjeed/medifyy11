"use client";

/** عميل السوبر أدمن — جلسة منفصلة كلياً عن جلسات المنشآت (مفاتيح تخزين ومسار تجديد مستقلان).
 *  كل المسارات تحت /api/v1/sa — قرار مالك 2026-07-15. */

import { ApiError } from "./api";
import type { Envelope, MdfError } from "./types";

const SA_TOKEN_KEY = "medify_sa_token";
const SA_ADMIN_KEY = "medify_sa_admin";

export interface SaAdmin {
  id: string;
  username: string;
  full_name: string;
  email: string | null;
  role: "super_admin";
}

function storageGet(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* جلسة بلا تخزين */
  }
}

function storageRemove(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    /* تجاهل */
  }
}

export function getSaToken(): string | null {
  return storageGet(SA_TOKEN_KEY);
}

export function setSaSession(token: string, admin: SaAdmin): void {
  storageSet(SA_TOKEN_KEY, token);
  storageSet(SA_ADMIN_KEY, JSON.stringify(admin));
}

export function getSaAdmin(): SaAdmin | null {
  const raw = storageGet(SA_ADMIN_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as SaAdmin;
  } catch {
    return null;
  }
}

export function clearSaSession(): void {
  storageRemove(SA_TOKEN_KEY);
  storageRemove(SA_ADMIN_KEY);
}

async function trySaRefresh(): Promise<boolean> {
  try {
    const response = await fetch("/api/v1/sa/auth/refresh", { method: "POST", credentials: "include" });
    if (!response.ok) return false;
    const body = (await response.json()) as Envelope<{ access_token: string }>;
    storageSet(SA_TOKEN_KEY, body.data.access_token);
    return true;
  } catch {
    return false;
  }
}

export interface SaApiOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
}

export async function saApi<T>(path: string, options: SaApiOptions = {}, retried = false): Promise<Envelope<T>> {
  const headers: Record<string, string> = {};
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const token = getSaToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(`/api/v1/sa${path}`, {
    method: options.method ?? "GET",
    headers,
    credentials: "include",
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });

  if (response.ok) {
    return (await response.json()) as Envelope<T>;
  }

  let err: MdfError = {
    code: "MDF-5001",
    message_ar: "خطأ داخلي غير مصنف.",
    message_en: "Unclassified error",
    details: {},
  };
  try {
    const parsed = (await response.json()) as { error?: MdfError };
    if (parsed.error) err = parsed.error;
  } catch {
    /* استجابة غير JSON */
  }

  if (err.code === "MDF-4012" && !retried && !path.startsWith("/auth/")) {
    if (await trySaRefresh()) {
      return saApi<T>(path, options, true);
    }
    clearSaSession();
    if (typeof window !== "undefined") {
      window.location.href = "/sa/login?expired=1";
    }
  }
  throw new ApiError(response.status, err);
}
