"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PrisonerTable } from "@/components/PrisonerTable";
import { Shell } from "@/components/Shell";
import { Card, ErrorBox, Loading, Notice, Stat } from "@/components/ui";
import { api, type PersonRow } from "@/lib/api";
import { apiErrorText, useI18n, type Key } from "@/lib/i18n";

interface District { district: string; prisoners: number; overdue: number; critical: number; review: number;
  urgent_default_bail: number; avg_detention_days: number; vulnerable: number; women: number; unassigned?: number }
interface Dash { districts: District[]; lawyer_workload: { lawyer: string; prisoners: number }[]; open_alerts: number;
  escalated_alerts: number; lawyers: { id: string; name: string }[] }
interface LawyerRow { id: string; name: string; active: boolean; status: string }

function heat(v: number, max: number) {
  const a = max ? v / max : 0;
  return { background: `rgba(180, 35, 24, ${0.08 + a * 0.55})`, color: a > 0.55 ? "#fff" : "#1b2233" };
}

export default function DlsaDashboard() {
  const { t, tk } = useI18n();
  const [d, setD] = useState<Dash | null>(null);
  const [rows, setRows] = useState<PersonRow[]>([]);
  const [lawyers, setLawyers] = useState<LawyerRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const load = () => {
    api<Dash>("/api/dashboard/dlsa").then(setD).catch((e) => setError(apiErrorText(t, e)));
    api<PersonRow[]>("/api/persons").then(setRows).catch(() => {});
    api<LawyerRow[]>("/api/lawyers").then(setLawyers).catch(() => {});
  };
  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (!d) return <Shell roles={["dlsa_admin"]}><ErrorBox error={error} />{!error && <Loading />}</Shell>;
  const cols: [keyof District, Key][] = [["prisoners", "undertrials"], ["overdue", "eligibleOverdue"], ["critical", "critical"],
    ["urgent_default_bail", "defaultBail"], ["review", "reviewCol"], ["unassigned", "unassignedCount"], ["vulnerable", "vulnerable"],
    ["avg_detention_days", "avgDetention"]];
  const max = (k: keyof District) => Math.max(...d.districts.map((x) => Number(x[k] ?? 0)));
  const active = lawyers.filter((l) => l.active);

  async function assign(pid: string, lawyerId: string) {
    setError(null);
    try { await api(`/api/persons/${pid}/assign`, { method: "POST", body: JSON.stringify({ lawyer_id: lawyerId }) }); setNotice(t("assigned")); load(); }
    catch (e) { setError(apiErrorText(t, e)); }
  }

  return (
    <Shell roles={["dlsa_admin"]}>
      <div className="flex flex-wrap justify-between gap-2 mb-4">
        <h1 className="text-2xl font-bold">{t("dlsaTitle")}</h1>
        <Link href="/lawyers" className="btn btn-ghost">{t("lawyers")}</Link>
      </div>
      <ErrorBox error={error} />
      <Notice text={notice} />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <Card><Stat label={t("undertrials")} value={d.districts.reduce((s, x) => s + x.prisoners, 0)} /></Card>
        <Card><Stat label={t("overdue479")} value={<span className="text-critical">{d.districts.reduce((s, x) => s + x.overdue, 0)}</span>} /></Card>
        <Card><Stat label={t("openAlerts")} value={d.open_alerts} /></Card>
        <Card><Stat label={t("escalatedAlerts")} value={<span className="text-urgent">{d.escalated_alerts}</span>} sub={t("escalatedSub")} /></Card>
      </div>
      <Card title={t("heatmap")} className="mb-5">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-muted"><th className="py-1 pr-3">{t("districtCol")}</th>
              {cols.map(([k, l]) => <th key={k} className="py-1 px-2 text-right">{t(l)}</th>)}</tr></thead>
            <tbody>
              {d.districts.map((x) => (
                <tr key={x.district} className="border-t border-line">
                  <th scope="row" className="py-1.5 pr-3 text-left font-medium">{x.district}</th>
                  {cols.map(([k]) => (
                    <td key={k} className="px-2 py-1.5 text-right tabular-nums font-semibold" style={k === "prisoners" ? undefined : heat(Number(x[k] ?? 0), max(k))}>
                      {x[k] ?? 0}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <div className="grid lg:grid-cols-3 gap-4">
        <Card title={t("workload")}>
          {d.lawyer_workload.length === 0 ? <p className="text-sm text-muted">{t("noItems")}</p> : (
            <ul className="space-y-2 text-sm">
              {d.lawyer_workload.map((l) => {
                const m = Math.max(...d.lawyer_workload.map((x) => x.prisoners));
                return (
                  <li key={l.lawyer}>
                    <div className="flex justify-between gap-2"><span>{l.lawyer}</span><span className="tabular-nums">{l.prisoners}</span></div>
                    <div className="h-2 bg-neutral-bg rounded"><div className="h-2 bg-navy-2 rounded" style={{ width: `${(l.prisoners / m) * 100}%` }} /></div>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
        <div className="lg:col-span-2 min-w-0">
          <PrisonerTable rows={rows} showUnassigned action={(r) => r.intake && r.intake !== "verified" ? (
            <span className="text-xs text-review">{tk("intake_", r.intake)} · {t("assignAfterReview")}</span>
          ) : (
            <label className="text-xs">
              <span className="sr-only">{t("assign")}</span>
              <select value={r.assigned_lawyer_id ?? ""} onChange={(e) => assign(r.id, e.target.value)}
                className="border border-line rounded px-1 py-0.5 max-w-40">
                <option value="" disabled>{t("assignLawyer")}</option>
                {active.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
            </label>
          )} />
        </div>
      </div>
    </Shell>
  );
}
