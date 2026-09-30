"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useI18n } from "@/lib/i18n";

export default function Error({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  const { t } = useI18n();
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <div role="alert" className="card p-6 max-w-md text-center space-y-3">
        <h1 className="text-2xl font-bold">{t("somethingWrong")}</h1>
        <p className="text-muted">{t("somethingWrongBody")}</p>
        <div className="flex justify-center gap-2">
          <button className="btn btn-primary" onClick={() => retry()}>{t("retry")}</button>
          <Link href="/" className="btn btn-ghost">{t("goHome")}</Link>
        </div>
      </div>
    </main>
  );
}
