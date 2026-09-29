"use client";

import type { CaseResult, PersonDetail } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Card, Severity, Stat, StatusBadge, fmtDate } from "./ui";

export function EligibilityPanel({ r, detail }: { r: CaseResult; detail: PersonDetail["case_details"][number] }) {
  const { t } = useI18n();
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <StatusBadge code={r.status} className="text-sm" />
          {r.findings.map((f) => <StatusBadge key={f.code} code={f.code} />)}
          <span className="text-sm text-muted">{detail.court} · {detail.case_numbers.join(" / ")} · CNR {detail.cnr}</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <Stat label={t("countedDetention")} value={`${r.counted_days}`} sub={`${r.custody_days} in custody − ${r.accused_days} accused delay`} />
          <Stat label={t("threshold")} value={r.threshold_days ?? "—"} sub={r.fraction ? `${r.fraction} of maximum` : undefined} />
          <Stat label={t("maximum")} value={r.max_days ?? "—"} sub={r.max_term ?? undefined} />
          <Stat label={r.eligible_from_date ? t("eligibleFrom") : t("projected")}
            value={<span className="text-base">{fmtDate(r.eligible_from_date ?? r.projected_date)}</span>}
            sub={r.days_overdue ? <span className="text-critical font-semibold">{r.days_overdue} {t("days")} {t("overdue")}</span> : undefined} />
          <Stat label={t("firstTime")} value={<span className="text-base">{r.first_time_offender == null ? "—" : r.first_time_offender ? "Yes" : "No"}</span>} />
        </div>
        {r.status === "ELIGIBLE" && <p className="mt-3 text-sm text-ok">{t("eligibleApply")}</p>}
      </Card>

      {r.needs_verification.length > 0 && (
        <Card title={<span className="text-review">{t("needsVerification")} ({r.needs_verification.length})</span>}>
          <ul className="list-disc pl-5 text-sm space-y-1">{r.needs_verification.map((n) => <li key={n}>{n}</li>)}</ul>
        </Card>
      )}

      {r.findings.length > 0 && (
        <Card title={t("findings")}>
          <ul className="space-y-2">
            {r.findings.map((f) => (
              <li key={f.code} className="text-sm flex gap-2"><Severity level={f.severity} /><span>{f.message}</span></li>
            ))}
          </ul>
        </Card>
      )}

      {Object.keys(r.interpretations).length > 0 && (
        <Card title={t("interpretations")}>
          <div className="grid md:grid-cols-2 gap-3">
            {Object.entries(r.interpretations).map(([k, v]) => (
              <div key={k} className="border border-line rounded-md p-3 text-sm">
                <div className="label mb-1">{k.replaceAll("_", " ")}</div>
                {v.status && <StatusBadge code={v.status} />}
                {v.summary && <p className="mt-1">{v.summary}</p>}
                {v.eligible_from && <p className="text-xs text-muted">eligible from {fmtDate(v.eligible_from)}</p>}
                {v.projected_date && <p className="text-xs text-muted">projected {fmtDate(v.projected_date)}</p>}
                {v.ceiling_date && <p className="text-xs text-muted">absolute ceiling {fmtDate(v.ceiling_date)}</p>}
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card title={t("charges")}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left"><tr className="text-muted">
              <th className="py-1 pr-3">Charge</th><th className="py-1 pr-3">{t("maximum")}</th>
              <th className="py-1 pr-3">{t("threshold")}</th><th className="py-1 pr-3">Legal data</th></tr></thead>
            <tbody>
              {r.charge_calcs.map((c) => {
                const rec = detail.charges.find((x) => `${x.act} ${x.section}` === c.charge.split(" (")[0])?.record;
                return (
                  <tr key={c.charge} className="border-t border-line align-top">
                    <td className="py-1.5 pr-3 font-medium">{c.charge}{rec && <div className="text-xs text-muted">{rec.title}</div>}</td>
                    <td className="py-1.5 pr-3">{c.max_term}{c.max_days ? ` (${c.max_days} d)` : ""}</td>
                    <td className="py-1.5 pr-3">{c.threshold_days ?? "—"}</td>
                    <td className="py-1.5 pr-3 text-xs">
                      {c.unverified.length > 0
                        ? <span className="text-review font-semibold">⚠ {t("needsLegalVerification")}</span>
                        : rec?.verified_by?.startsWith("DEMO") ? <span className="text-urgent">demo-verified only</span>
                        : <span className="text-ok">verified</span>}
                      {c.special_law && <div className="text-urgent">special law</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {r.flags.length > 0 && (
        <Card title={t("flags")}>
          <ul className="space-y-1.5">
            {r.flags.map((f, i) => <li key={i} className="text-sm flex gap-2"><Severity level={f.severity} /><span>{f.message}</span></li>)}
          </ul>
        </Card>
      )}

      <Card title={t("trace")}>
        <ol className="space-y-2 text-sm list-decimal pl-5">
          {r.trace.map((s, i) => (
            <li key={i}>
              <span>{s.text}</span>
              {s.refs.length > 0 && <span className="text-xs text-muted"> — {s.refs.join("; ")}</span>}
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}
