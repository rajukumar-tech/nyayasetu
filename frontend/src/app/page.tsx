"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { homeFor, useAuth } from "@/lib/auth";

export default function Home() {
  const { user, ready } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!ready) return;
    router.replace(user ? homeFor(user.role) : "/login");
  }, [ready, user, router]);
  return <p className="p-8 text-muted" role="status">Loading…</p>;
}
