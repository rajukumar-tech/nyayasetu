"use client";

import { useEffect, useState } from "react";
import { PrisonerTable } from "@/components/PrisonerTable";
import { Shell } from "@/components/Shell";
import { Card, ErrorBox, Loading, Stat } from "@/components/ui";
import { api, type PersonRow } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

interface District { district: string; prisoners: number; overdue: number; critical: number; review: number;
  urgent_default_bail: number; avg_detention_days: number; vulnerable: number; women: number }
interface Dash { districts: District[]; lawyer_workload: { lawyer: string; prisoners: number }[]; open_alerts: number;
  escalated_alerts: number; lawyers: { id: string; name: string }[] }

function heat(v: number, max: number) {
  const a = max ? v / max : 0;
  return { background: `rgba(180, 35, 24, ${0.08 + a * 0.55})`, color: a > 0.55 ? "#fff" : "#1b2233" };
}

export default function DlsaDashboard() {
  const { t } = useI18n();
  const [d, setD] = useState<Dash | null>(null);
  const [rows, setRows] = useState<PersonRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const load = () => {
    api<Dash>("/api/dashboard/dlsa").then(setD).catch((e) => setError(e.message));
    api<PersonRow[]>("/api/persons").then(setRows).catch(() => {});
  };
  useEffect(load, []);
  if (!d) return <Shell roles={["dlsa_admin"]}><ErrorBox error={error} /><Loading /></Shell>;
  const cols: [keyof District, string][] = [["prisoners", "Undertrials"], ["overdue", "Eligible/overdue"], ["critical", "Critical"],
    ["urgent_default_bail", "Default bail"], ["review", "Review"], ["vulnerable", t("vulnerable")], ["avg_detention_days", t("avgDetention")]];
  const max = (k: keyof District) => Math.max(...d.districts.map((x) => Number(x[k])));

  async function assign(pid: string, lawyerId: string) {
    try { await api(`/api/persons/${pid}/assign`, { method: "POST", body: JSON.stringify({ lawyer_id: lawyerId }) }); load(); }
    catch (e) { setError((e as Error).message); }
  }

  return (
    <Shell roles={["dlsa_admin"]}>
      <h1 className="text-2xl font-bold mb-4">District Legal Services Authority / UTRC</h1>
      <ErrorBox error={error} />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <Card><Stat label="Undertrials" value={d.districts.reduce((s, x) => s + x.prisoners, 0)} /></Card>
        <Card><Stat label="Overdue (479)" value={<span className="text-critical">{d.districts.reduce((s, x) => s + x.overdue, 0)}</span>} /></Card>
        <Card><Stat label="Open alerts" value={d.open_alerts} /></Card>
        <Card><Stat label="Escalated" value={<span className="text-urgent">{d.escalated_alerts}</span>} sub="unacknowledged past the limit" /></Card>
      </div>
      <Card title={t("heatmap")} className="mb-5">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-muted"><th className="py-1 pr-3">District</th>
              {cols.map(([k, l]) => <th key={k} className="py-1 px-2 text-right">{l}</th>)}</tr></thead>
            <tbody>
              {d.districts.map((x) => (
                <tr key={x.district} className="border-t border-line">
                  <th scope="row" className="py-1.5 pr-3 text-left font-medium">{x.district}</th>
                  {cols.map(([k]) => (
                    <td key={k} className="px-2 py-1.5 text-right tabular-nums font-semibold" style={k === "prisoners" ? undefined : heat(Number(x[k]), max(k))}>
                      {x[k]}
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
          <ul className="space-y-2 text-sm">
            {d.lawyer_workload.map((l) => {
              const m = Math.max(...d.lawyer_workload.map((x) => x.prisoners));
              return (
                <li key={l.lawyer}>
                  <div className="flex justify-between"><span>{l.lawyer}</span><span className="tabular-nums">{l.prisoners}</span></div>
                  <div className="h-2 bg-neutral-bg rounded"><div className="h-2 bg-navy-2 rounded" style={{ width: `${(l.prisoners / m) * 100}%` }} /></div>
                </li>
              );
            })}
          </ul>
        </Card>
        <div className="lg:col-span-2">
          <PrisonerTable rows={rows} action={(r) => (
            <label className="text-xs">
              <span className="sr-only">{t("assign")}</span>
              <select defaultValue={r.assigned_lawyer_id ?? ""} onChange={(e) => assign(r.id, e.target.value)}
                className="border border-line rounded px-1 py-0.5 max-w-36">
                <option value="" disabled>{t("assign")}…</option>
                {d.lawyers.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
            </label>
          )} />
        </div>
      </div>
    </Shell>
  );
}
