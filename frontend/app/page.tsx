"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { getSessionUser, getToken } from "@/lib/api";

/** الجذر: توجيه حسب الجلسة والدور. */
export default function RootRedirect() {
  const router = useRouter();
  useEffect(() => {
    const user = getSessionUser();
    if (user === null || getToken() === null) router.replace("/login");
    else router.replace(user.role === "admin" ? "/admin" : "/doctor");
  }, [router]);
  return null;
}
