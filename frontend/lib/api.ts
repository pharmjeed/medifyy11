"use client";

/** عميل API — الغلاف الموحد + تجديد صامت عند MDF-4012 + رفع ApiError برمز MDF. */

import type { Envelope, MdfError, SessionUser } from "./types";

const TOKEN_KEY = "medify_token";
const USER_KEY = "medify_user";

export class ApiError extends Error {
  code: string;
  messageAr: string;
  details: Record<string, unknown>;
  status: number;

  constructor(status: number, err: MdfError) {
    super(`${err.code}: ${err.message_en}`);
    this.status = status;
    this.code = err.code;
    this.messageAr = err.message_ar;
    this.details = err.details ?? {};
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setSession(token: string, user: SessionUser): void {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getSessionUser(): SessionUser | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as SessionUser;
  } catch {
    return null;
  }
}

export function clearSession(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

async function tryRefresh(): Promise<boolean> {
  try {
    const response = await fetch("/api/v1/auth/refresh", { method: "POST", credentials: "include" });
    if (!response.ok) return false;
    const body = (await response.json()) as Envelope<{ access_token: string }>;
    window.localStorage.setItem(TOKEN_KEY, body.data.access_token);
    return true;
  } catch {
    return false;
  }
}

export interface ApiOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
  /** يعيد الاستجابة الكاملة مع ترويسات (ETag) */
  raw?: boolean;
}

export async function api<T>(path: string, options: ApiOptions = {}): Promise<Envelope<T>> {
  const result = await apiWithHeaders<T>(path, options);
  return result.body;
}

export async function apiWithHeaders<T>(
  path: string,
  options: ApiOptions = {},
  retried = false,
): Promise<{ body: Envelope<T>; headers: Headers }> {
  const headers: Record<string, string> = { ...options.headers };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(`/api/v1${path}`, {
    method: options.method ?? "GET",
    headers,
    credentials: "include",
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });

  if (response.ok) {
    return { body: (await response.json()) as Envelope<T>, headers: response.headers };
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

  // جلسة منتهية → تجديد صامت ثم إعادة الطلب مرة واحدة (سلوك MDF-4012 في DOC-13)
  if (err.code === "MDF-4012" && !retried && !path.startsWith("/auth/")) {
    if (await tryRefresh()) {
      return apiWithHeaders<T>(path, options, true);
    }
    clearSession();
    if (typeof window !== "undefined") {
      window.location.href = "/login?expired=1";
    }
  }
  throw new ApiError(response.status, err);
}

export function wsUrl(visitId: string): string {
  const base =
    process.env.NEXT_PUBLIC_WS_BASE ??
    (typeof window !== "undefined" && window.location.protocol === "https:"
      ? `wss://${window.location.host}`
      : "ws://localhost:8000");
  return `${base}/ws/visits/${visitId}/transcribe?token=${getToken() ?? ""}`;
}

export const SHOW_SPEC_IDS = process.env.NEXT_PUBLIC_SHOW_SPEC_IDS === "true";
