"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { PersonRow } from "@/lib/api";
import { useI18n, type Key } from "@/lib/i18n";
import { DemoBadge, StatusBadge } from "./ui";

export function PrisonerTable({ rows, showPriority = true, action, showUnassigned = false }: {
  rows: PersonRow[]; showPriority?: boolean; action?: (r: PersonRow) => React.ReactNode; showUnassigned?: boolean;
}) {
  const { t, tk, fd } = useI18n();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const shown = useMemo(() => rows.filter((r) => {
    if (q && !r.name.toLowerCase().includes(q.toLowerCase())) return false;
    if (filter === "urgent") return /^(CRITICAL|URGENT)/.test(r.urgency) || r.status === "ELIGIBLE";
    if (filter === "review") return (r.status ?? "").startsWith("REVIEW");
    if (filter === "unassigned") return !r.assigned_lawyer_id;
    return true;
  }), [rows, q, filter]);
  const filters: [string, Key][] = [["all", "filter_all"], ["urgent", "filter_urgent"], ["review", "filter_review"],
    ...(showUnassigned ? [["unassigned", "filter_unassigned"] as [string, Key]] : [])];
  const vuln = (r: PersonRow) => r.vulnerability.map((v) => tk("vuln_", v)).join(", ");

  return (
    <div>
      <div className="flex flex-wrap gap-2 mb-3">
        <label className="sr-only" htmlFor="q">{t("search")}</label>
        <input id="q" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("search")}
          className="border border-line rounded-md px-3 py-1.5 text-sm bg-surface w-full sm:w-64" />
        <div role="group" aria-label={t("filter")} className="flex flex-wrap gap-1">
          {filters.map(([k, l]) => (
            <button key={k} onClick={() => setFilter(k)} aria-pressed={filter === k}
              className={`btn ${filter === k ? "btn-primary" : "btn-ghost"} !py-1`}>{t(l)}</button>
          ))}
        </div>
        <span className="ml-auto text-sm text-muted self-center">{t("showing", { shown: shown.length, total: rows.length })}</span>
      </div>

      {/* desktop table */}
      <div className="card overflow-x-auto hidden md:block">
        <table className="w-full text-sm">
          <caption className="sr-only">{t("tableCaption")}</caption>
          <thead className="bg-neutral-bg text-left">
            <tr>
              <th scope="col" className="px-3 py-2">{t("name")}</th>
              <th scope="col" className="px-3 py-2">{t("status")}</th>
              <th scope="col" className="px-3 py-2">{t("charges")}</th>
              <th scope="col" className="px-3 py-2 text-right">{t("custody")}</th>
              <th scope="col" className="px-3 py-2">{t("eligibleFrom")}</th>
              {showPriority && <th scope="col" className="px-3 py-2 text-right">{t("priority")}</th>}
              {action && <th scope="col" className="px-3 py-2"><span className="sr-only">{t("action")}</span></th>}
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.id} className="border-t border-line hover:bg-paper align-top">
                <td className="px-3 py-2 min-w-40">
                  <Link href={`/prisoners/${r.id}`} className="font-semibold text-navy-2 underline-offset-2 hover:underline">{r.name}</Link>
                  <DemoBadge label={r.demo_label} />
                  <div className="text-xs text-muted">{r.relation} {r.relative}{r.relative ? " · " : ""}{r.jail}</div>
                  {r.vulnerability.length > 0 && <div className="text-xs text-accent">{vuln(r)}</div>}
                  {showUnassigned && !r.assigned_lawyer_id && <div className="text-xs text-urgent font-semibold">{t("unassigned")}</div>}
                </td>
                <td className="px-3 py-2 space-y-1">
                  <StatusBadge code={r.urgency} />
                  {r.status && r.status !== r.urgency && <div><StatusBadge code={r.status} /></div>}
                  {r.needs_verification > 0 && <div className="text-xs text-review">{t("toVerify", { n: r.needs_verification })}</div>}
                </td>
                <td className="px-3 py-2 text-xs">{r.cases.flatMap((c) => c.charges).join(", ")}</td>
                <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{r.custody_days} {t("days")}</td>
                <td className="px-3 py-2">
                  {r.eligible_from_date ? fd(r.eligible_from_date) : "—"}
                  {r.days_overdue ? <div className="text-xs text-critical font-semibold">{r.days_overdue} {t("days")} {t("overdue")}</div> : null}
                </td>
                {showPriority && <td className="px-3 py-2 text-right tabular-nums">{r.priority ?? "—"}</td>}
                {action && <td className="px-3 py-2">{action(r)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
        {shown.length === 0 && <p className="p-4 text-muted">{t("noItems")}</p>}
      </div>

      {/* mobile cards */}
      <ul className="md:hidden space-y-2">
        {shown.map((r) => (
          <li key={r.id} className="card p-3">
            <div className="flex flex-wrap justify-between gap-2">
              <span><Link href={`/prisoners/${r.id}`} className="font-semibold text-navy-2">{r.name}</Link><DemoBadge label={r.demo_label} /></span>
              <StatusBadge code={r.urgency} />
            </div>
            <p className="text-xs text-muted mt-1">{r.cases.flatMap((c) => c.charges).join(", ")} · {r.custody_days} {t("days")}</p>
            {r.days_overdue ? <p className="text-xs text-critical font-semibold">{r.days_overdue} {t("days")} {t("overdue")}</p> : null}
            {showUnassigned && !r.assigned_lawyer_id && <p className="text-xs text-urgent font-semibold">{t("unassigned")}</p>}
            {action && <div className="mt-2">{action(r)}</div>}
          </li>
        ))}
        {shown.length === 0 && <li className="text-muted">{t("noItems")}</li>}
      </ul>
      {showPriority && <p className="text-xs text-muted mt-2">{t("priorityNote")}</p>}
    </div>
  );
}
