"use client";

import Link from "next/link";
import { useI18n } from "@/lib/i18n";

export default function NotFound() {
  const { t } = useI18n();
  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <div className="card p-6 max-w-md text-center space-y-3">
        <h1 className="text-2xl font-bold">{t("pageNotFound")}</h1>
        <p className="text-muted">{t("pageNotFoundBody")}</p>
        <Link href="/" className="btn btn-primary">{t("goHome")}</Link>
      </div>
    </main>
  );
}
