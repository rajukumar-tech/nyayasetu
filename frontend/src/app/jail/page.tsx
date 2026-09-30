"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PrisonerTable } from "@/components/PrisonerTable";
import { Shell } from "@/components/Shell";
import { Card, ErrorBox, Loading, Stat } from "@/components/ui";
import { api, type PersonRow } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { apiErrorText, useI18n } from "@/lib/i18n";

export default function JailDashboard() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [rows, setRows] = useState<PersonRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api<PersonRow[]>("/api/persons").then(setRows).catch((e) => setError(apiErrorText(t, e))); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const eligible = rows?.filter((r) => r.status === "ELIGIBLE" || /^(CRITICAL|URGENT)/.test(r.urgency)) ?? [];
  return (
    <Shell roles={["jail_staff"]}>
      <div className="flex flex-wrap justify-between gap-2">
        <h1 className="text-2xl font-bold">{user?.jail}</h1>
        <Link href="/prisoners/new" className="btn btn-primary">{t("addPrisoner")}</Link>
      </div>
      <p className="text-sm text-muted mb-4">{t("jailIntro")}</p>
      <ErrorBox error={error} />
      {!rows ? (!error && <Loading />) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-5">
            <Card><Stat label={t("undertrials")} value={rows.length} /></Card>
            <Card><Stat label={t("actNow")} value={<span className="text-critical">{eligible.length}</span>} sub={t("actNowSub")} /></Card>
            <Card><Stat label={t("stat_review")} value={rows.filter((r) => (r.status ?? "").startsWith("REVIEW")).length} /></Card>
          </div>
          <PrisonerTable rows={rows} showPriority={false} action={(r) =>
            (r.status === "ELIGIBLE" || r.urgency === "CRITICAL_MUST_RELEASE") ? (
              <Link href={`/prisoners/${r.id}`} className="btn btn-primary !py-1 !text-xs">{t("superintendentApp")}</Link>
            ) : null} />
          <p className="text-xs text-muted mt-3">{t("jailNote")}</p>
        </>
      )}
    </Shell>
  );
}
