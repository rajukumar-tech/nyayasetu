"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PrisonerTable } from "@/components/PrisonerTable";
import { Shell } from "@/components/Shell";
import { Card, ErrorBox, Loading, Stat } from "@/components/ui";
import { api, type PersonRow } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";

export default function JailDashboard() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [rows, setRows] = useState<PersonRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api<PersonRow[]>("/api/persons").then(setRows).catch((e) => setError(e.message)); }, []);
  const eligible = rows?.filter((r) => r.status === "ELIGIBLE" || /^(CRITICAL|URGENT)/.test(r.urgency)) ?? [];
  return (
    <Shell roles={["jail_staff"]}>
      <h1 className="text-2xl font-bold">{user?.jail}</h1>
      <p className="text-sm text-muted mb-4">Undertrials eligible for release or overdue — the superintendent must apply to the court when the threshold is reached.</p>
      <ErrorBox error={error} />
      {!rows ? <Loading /> : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-5">
            <Card><Stat label="Undertrials" value={rows.length} /></Card>
            <Card><Stat label="Act now" value={<span className="text-critical">{eligible.length}</span>} sub="eligible, overdue or critical" /></Card>
            <Card><Stat label="Needs review" value={rows.filter((r) => (r.status ?? "").startsWith("REVIEW")).length} /></Card>
          </div>
          <PrisonerTable rows={rows} showPriority={false} action={(r) =>
            (r.status === "ELIGIBLE" || r.urgency === "CRITICAL_MUST_RELEASE") ? (
              <Link href={`/prisoners/${r.id}`} className="btn btn-primary !py-1 !text-xs whitespace-nowrap">{t("superintendentApp")}</Link>
            ) : null} />
          <p className="text-xs text-muted mt-3">Jail staff see eligibility and alerts; privileged Defense Insights are visible only to the assigned lawyer.</p>
        </>
      )}
    </Shell>
  );
}
