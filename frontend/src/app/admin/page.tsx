"use client";

import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { Card, ErrorBox, Loading } from "@/components/ui";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

interface Rec { key: string; title: string; punishment_summary: string; max: string | null; kind: string; verified: boolean;
  verified_by?: string; source: string; notes?: string; special_law: boolean }
interface Legal { version: string; records: Rec[]; rules: { key: string; ref: string; verified: boolean }[]; unverified: number; demo_verified_only: number }
interface AuditRow { id: number; ts: string; role: string; action: string; entity_type: string; entity_id?: string; detail?: string }

export default function Admin() {
  const { t } = useI18n();
  const [legal, setLegal] = useState<Legal | null>(null);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const load = () => {
    api<Legal>("/api/legal/records").then(setLegal).catch((e) => setError(e.message));
    api<AuditRow[]>("/api/admin/audit?limit=150").then(setAudit).catch(() => {});
  };
  useEffect(load, []);

  async function verify(key: string, verified: boolean) {
    const note = window.prompt(`What did you check for ${key}? (e.g. "India Code PDF, punishment clause")`);
    if (!note || note.length < 5) return;
    try {
      await api(`/api/legal/records/${encodeURIComponent(key)}/verify`, { method: "POST", body: JSON.stringify({ verified, note }) });
      load();
    } catch (e) { setError((e as Error).message); }
  }
  async function nightly() {
    const r = await api<{ persons: number; alerts_created: number; escalated: number }>("/api/admin/run-nightly", { method: "POST" });
    setMsg(`Recomputed ${r.persons} prisoners · ${r.alerts_created} new alerts · ${r.escalated} escalated.`);
  }

  return (
    <Shell roles={["system_admin"]}>
      <div className="flex flex-wrap justify-between gap-2 mb-4">
        <h1 className="text-2xl font-bold">{t("admin")}</h1>
        <button className="btn btn-primary" onClick={nightly}>{t("runNightly")}</button>
      </div>
      <ErrorBox error={error} />
      {msg && <p role="status" className="card bg-ok-bg text-ok p-3 text-sm mb-3">{msg}</p>}
      {!legal ? <Loading /> : (
        <Card title={`${t("legalData")} · version ${legal.version}`} className="mb-5"
          actions={<span className="text-sm font-semibold"><span className="text-review">{legal.unverified} unverified</span>
            {legal.demo_verified_only > 0 && <span className="text-critical"> · {legal.demo_verified_only} demo-verified only (NOT legally checked)</span>}</span>}>
          <p className="text-sm text-muted mb-2">Every record must be checked against official text (India Code / Gazette) before relying on it.
            Records marked “DEMO SEED” were verified only to make the demo run — not a legal check.</p>
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter (e.g. IPC:379)" aria-label="Filter records"
            className="border border-line rounded-md px-3 py-1.5 text-sm mb-2 w-64" />
          <div className="overflow-x-auto max-h-[28rem]">
            <table className="w-full text-sm">
              <thead className="text-left text-muted sticky top-0 bg-surface"><tr><th className="py-1 pr-2">Record</th><th>Maximum</th><th>Status</th><th /></tr></thead>
              <tbody>
                {[...legal.records.map((r) => ({ ...r, isRule: false })),
                  ...legal.rules.map((r) => ({ key: r.key, title: r.ref, punishment_summary: "", max: null, kind: "rule", verified: r.verified,
                    source: "", special_law: false, isRule: true, verified_by: undefined }))]
                  .filter((r) => !filter || r.key.toLowerCase().includes(filter.toLowerCase()) || r.title.toLowerCase().includes(filter.toLowerCase()))
                  .map((r) => (
                    <tr key={r.key} className="border-t border-line align-top">
                      <td className="py-1.5 pr-2"><div className="font-medium">{r.key}</div><div className="text-xs text-muted">{r.title}</div>
                        {r.punishment_summary && <div className="text-xs">{r.punishment_summary}</div>}</td>
                      <td className="pr-2">{r.max ?? "—"}</td>
                      <td className="pr-2 text-xs">{r.verified
                        ? <span className={r.verified_by?.startsWith("DEMO") ? "text-urgent" : "text-ok"}>verified{r.verified_by ? ` — ${r.verified_by}` : ""}</span>
                        : <span className="text-review font-semibold">{t("needsLegalVerification")}</span>}</td>
                      <td><button className="btn btn-ghost !py-0.5 !text-xs" onClick={() => verify(r.key, !r.verified)}>{r.verified ? "Mark unverified" : t("verify")}</button></td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      <Card title={t("audit")}>
        <div className="overflow-x-auto max-h-96">
          <table className="w-full text-xs">
            <thead className="text-left text-muted"><tr><th className="py-1">Time</th><th>Role</th><th>Action</th><th>Entity</th><th>Detail</th></tr></thead>
            <tbody>{audit.map((a) => (
              <tr key={a.id} className="border-t border-line"><td className="py-0.5 pr-2 whitespace-nowrap">{new Date(a.ts).toLocaleString()}</td>
                <td className="pr-2">{a.role}</td><td className="pr-2">{a.action}</td><td className="pr-2">{a.entity_type} {a.entity_id}</td><td>{a.detail}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </Card>
    </Shell>
  );
}
