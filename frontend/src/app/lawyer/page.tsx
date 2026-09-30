"use client";

import { useEffect, useState } from "react";
import { PrisonerTable } from "@/components/PrisonerTable";
import { Shell } from "@/components/Shell";
import { Card, ErrorBox, Loading, Stat } from "@/components/ui";
import { api, type PersonRow } from "@/lib/api";
import { apiErrorText, useI18n } from "@/lib/i18n";

export default function LawyerDashboard() {
  const { t } = useI18n();
  const [rows, setRows] = useState<PersonRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<PersonRow[]>("/api/persons").then(setRows).catch((e) => setError(apiErrorText(t, e)));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const count = (f: (r: PersonRow) => boolean) => rows?.filter(f).length ?? 0;
  return (
    <Shell roles={["legal_aid_lawyer"]}>
      <h1 className="text-2xl font-bold mb-4">{t("myPrisoners")}</h1>
      <ErrorBox error={error} />
      {!rows ? (!error && <Loading />) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
            <Card><Stat label={t("stat_critical")} value={<span className="text-critical">{count((r) => r.urgency.startsWith("CRITICAL"))}</span>} sub={t("stat_critical_sub")} /></Card>
            <Card><Stat label={t("stat_defaultBail")} value={<span className="text-urgent">{count((r) => r.urgency === "URGENT_DEFAULT_BAIL")}</span>} sub={t("stat_defaultBail_sub")} /></Card>
            <Card><Stat label={t("stat_eligible")} value={<span className="text-ok">{count((r) => r.status === "ELIGIBLE")}</span>} sub={t("stat_eligible_sub")} /></Card>
            <Card><Stat label={t("stat_review")} value={<span className="text-review">{count((r) => (r.status ?? "").startsWith("REVIEW"))}</span>} sub={t("stat_review_sub")} /></Card>
          </div>
          {rows.length === 0 ? <p className="card p-4 text-muted">{t("zeroAssigned")}</p> : <PrisonerTable rows={rows} />}
        </>
      )}
    </Shell>
  );
}
