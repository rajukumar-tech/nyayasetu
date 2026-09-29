"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { ErrorBox, Loading, Severity } from "@/components/ui";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

interface Alert { id: string; person_id: string; person: string; kind: string; severity: string; message: string;
  created_at: string; escalated: boolean }

export default function Alerts() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Alert[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => api<Alert[]>("/api/alerts").then(setRows).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);
  async function ack(id: string) {
    await api(`/api/alerts/${id}/ack`, { method: "POST" });
    load();
  }
  const order = ["critical", "high", "medium", "low"];
  return (
    <Shell roles={["legal_aid_lawyer", "jail_staff", "dlsa_admin"]}>
      <h1 className="text-2xl font-bold mb-4">{t("alerts")}</h1>
      <ErrorBox error={error} />
      {!rows ? <Loading /> : rows.length === 0 ? <p className="text-muted">{t("noItems")}</p> : (
        <ul className="space-y-2">
          {[...rows].sort((a, b) => order.indexOf(a.severity) - order.indexOf(b.severity)).map((a) => (
            <li key={a.id} className="card p-3 flex flex-wrap gap-3 items-center">
              <Severity level={a.severity} />
              <div className="flex-1 min-w-60">
                <Link href={`/prisoners/${a.person_id}`} className="font-semibold text-navy-2 hover:underline">{a.person}</Link>
                <p className="text-sm">{a.message}</p>
                <p className="text-xs text-muted">{a.kind} · {new Date(a.created_at).toLocaleString()}{a.escalated ? " · escalated" : ""}</p>
              </div>
              <button className="btn btn-ghost !py-1" onClick={() => ack(a.id)}>{t("acknowledge")}</button>
            </li>
          ))}
        </ul>
      )}
    </Shell>
  );
}
