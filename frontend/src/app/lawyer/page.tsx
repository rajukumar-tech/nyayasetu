"use client";

import { useEffect, useState } from "react";
import { PrisonerTable } from "@/components/PrisonerTable";
import { Shell } from "@/components/Shell";
import { Card, ErrorBox, Loading, Stat } from "@/components/ui";
import { api, type PersonRow } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function LawyerDashboard() {
  const { t } = useI18n();
  const [rows, setRows] = useState<PersonRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<PersonRow[]>("/api/persons").then(setRows).catch((e) => setError(e.message));
  }, []);
  const count = (f: (r: PersonRow) => boolean) => rows?.filter(f).length ?? 0;
  return (
    <Shell roles={["legal_aid_lawyer"]}>
      <h1 className="text-2xl font-bold mb-4">{t("myPrisoners")}</h1>
      <ErrorBox error={error} />
      {!rows ? <Loading /> : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
            <Card><Stat label="Critical" value={<span className="text-critical">{count((r) => r.urgency.startsWith("CRITICAL"))}</span>} sub="detained beyond limits" /></Card>
            <Card><Stat label="Default bail" value={<span className="text-urgent">{count((r) => r.urgency === "URGENT_DEFAULT_BAIL")}</span>} sub="apply before charge sheet" /></Card>
            <Card><Stat label="Eligible (479)" value={<span className="text-ok">{count((r) => r.status === "ELIGIBLE")}</span>} sub="application due" /></Card>
            <Card><Stat label="Needs review" value={<span className="text-review">{count((r) => (r.status ?? "").startsWith("REVIEW"))}</span>} sub="facts or law to verify" /></Card>
          </div>
          <PrisonerTable rows={rows} />
        </>
      )}
    </Shell>
  );
}
