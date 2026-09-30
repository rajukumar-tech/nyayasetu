"use client";

import type { CaseResult, Finding, PersonDetail } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Card, Severity, Stat, StatusBadge } from "./ui";

const DEFAULT_BAIL = new Set(["URGENT_DEFAULT_BAIL", "DEFAULT_BAIL_WINDOW_SOON", "DEFAULT_BAIL_RIGHT_ASSERTED",
  "DEFAULT_BAIL_RIGHT_LOST", "DEFAULT_BAIL_REVIEW"]);

function Recorded({ text }: { text: string }) {
  const { t } = useI18n();
  return (
    <details className="text-xs text-muted mt-0.5">
      <summary className="cursor-pointer">{t("recordedDetail")}</summary>
      <p lang="en" className="mt-1">{text}</p>
    </details>
  );
}

function FindingRow({ f }: { f: Finding }) {
  const { ts, fd } = useI18n();
  return (
    <li className="text-sm">
      <div className="flex flex-wrap items-center gap-2"><Severity level={f.severity} /><StatusBadge code={f.code} />
        {f.date && <span className="text-xs text-muted">{fd(f.date)}</span>}</div>
      <span className="sr-only">{ts(f.code)}</span>
      <Recorded text={f.message} />
    </li>
  );
}

export function EligibilityPanel({ r, detail }: { r: CaseResult; detail: PersonDetail["case_details"][number] }) {
  const { t, ts, tk, fd, fterm } = useI18n();
  const dbFindings = r.findings.filter((f) => DEFAULT_BAIL.has(f.code));
  const other = r.findings.filter((f) => !DEFAULT_BAIL.has(f.code));
  const frac = r.fraction === "1/3" ? "⅓" : r.fraction === "1/2" ? "½" : r.fraction;
  const most = r.charge_calcs.find((c) => c.max_days === r.max_days && r.max_days != null) ?? r.charge_calcs[0];
  const left = r.threshold_days != null ? r.threshold_days - r.counted_days : null;
  const hasNumbers = r.threshold_days != null && r.max_days != null;
  const lines: string[] = [];
  if (!["NOT_APPLICABLE", "CRITICAL_ACQUITTED_DETAINED"].includes(r.status)) {
    lines.push(t("calc_custody", { n: r.custody_days }), t("calc_accused", { n: r.accused_days }));
    if (r.flags.some((f) => f.code === "DELAY_ATTRIBUTION_UNCERTAIN")) lines.push(t("calc_uncertain"));
    lines.push(t("calc_counted", { custody: r.custody_days, accused: r.accused_days, counted: r.counted_days }));
    if (hasNumbers && most) {
      lines.push(t("calc_max", { charge: most.charge, term: fterm(most.max_term), days: r.max_days }));
      lines.push(r.first_time_offender ? t("calc_fraction_first") : t("calc_fraction_repeat"));
      lines.push(t("calc_threshold", { fraction: frac, max: r.max_days, thr: r.threshold_days }));
    }
  }
  let verdict: string;
  if (r.status === "ELIGIBLE") verdict = t("calc_eligible", { counted: r.counted_days, thr: r.threshold_days, date: fd(r.eligible_from_date), over: r.days_overdue });
  else if (r.status === "NOT_YET") verdict = t("calc_notyet", { counted: r.counted_days, thr: r.threshold_days, left, date: fd(r.projected_date) });
  else if (r.status === "CRITICAL_MUST_RELEASE") verdict = t("calc_critical", { counted: r.counted_days, max: r.max_days, date: fd(r.eligible_from_date), over: r.days_overdue });
  else if (r.status === "EXCLUDED_479") verdict = t("calc_excluded");
  else if (r.status === "CRITICAL_ACQUITTED_DETAINED") verdict = t("calc_acquitted");
  else if (r.status === "NOT_APPLICABLE") verdict = t("calc_notApplicable");
  else verdict = t("calc_review");

  return (
    <div className="space-y-4">
      {/* ---------------------------------------------------------------- Section 479 */}
      <Card title={t("s479Title")}>
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <StatusBadge code={r.status} className="text-sm" />
          <span className="text-sm text-muted">{detail.court} · {detail.case_numbers.join(" / ")} · CNR {detail.cnr} · {tk("caseStatus_", detail.status)}</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <Stat label={t("countedDetention")} value={`${r.counted_days}`} sub={t("countedSub", { custody: r.custody_days, accused: r.accused_days })} />
          <Stat label={t("threshold")} value={r.threshold_days ?? "—"} sub={frac ? t("thresholdSub", { fraction: frac }) : undefined} />
          <Stat label={t("maximum")} value={r.max_days ?? "—"} sub={r.max_term ? fterm(r.max_term) : undefined} />
          <Stat label={r.eligible_from_date ? t("eligibleFrom") : t("projected")}
            value={<span className="text-base">{fd(r.eligible_from_date ?? r.projected_date)}</span>}
            sub={r.days_overdue ? <span className="text-critical font-semibold">{r.days_overdue} {t("days")} {t("overdue")}</span> : undefined} />
          <Stat label={t("firstTime")} value={<span className="text-base">{r.first_time_offender == null ? "—" : r.first_time_offender ? t("yes") : t("no")}</span>} />
        </div>
        <div className="mt-4 rounded-md bg-paper p-3">
          <p className="label mb-1">{t("calcTitle")}</p>
          <ol className="text-sm space-y-0.5 list-decimal pl-5">{lines.map((l) => <li key={l}>{l}</li>)}</ol>
          <p className={`text-sm font-semibold mt-2 ${r.status === "ELIGIBLE" ? "text-ok" : r.status.startsWith("CRITICAL") ? "text-critical" : r.status.startsWith("REVIEW") ? "text-review" : ""}`}>{verdict}</p>
        </div>
        {r.status === "ELIGIBLE" && <p className="mt-3 text-sm text-ok">{t("eligibleApply")}</p>}
        <p className="mt-2 text-xs text-muted">{t("decides")}</p>
      </Card>

      {r.needs_verification.length > 0 && (
        <Card title={<span className="text-review">{t("needsVerification")} ({r.needs_verification.length})</span>}>
          <ul lang="en" className="list-disc pl-5 text-sm space-y-1">{r.needs_verification.map((n) => <li key={n}>{n}</li>)}</ul>
          <p className="text-xs text-muted mt-1">{t("recordedDetail")}</p>
        </Card>
      )}

      {/* ---------------------------------------------------------------- default bail (separate route) */}
      <Card title={t("defaultBailTitle")}>
        <dl className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm mb-2">
          <div><dt className="label">{t("firstRemandDate")}</dt><dd>{fd(detail.first_remand_date)}</dd></div>
          <div><dt className="label">{t("chargeSheetDate")}</dt><dd>{fd(detail.charge_sheet_date)}</dd></div>
        </dl>
        {dbFindings.length ? <ul className="space-y-2">{dbFindings.map((f) => <FindingRow key={f.code} f={f} />)}</ul>
          : <p className="text-sm text-muted">{detail.first_remand_date ? t("defaultBail_none") : t("defaultBail_noData")}</p>}
      </Card>

      {/* ---------------------------------------------------------------- other routes */}
      {other.length > 0 && (
        <Card title={t("otherRoutesTitle")}>
          <ul className="space-y-2">{other.map((f) => <FindingRow key={f.code} f={f} />)}</ul>
        </Card>
      )}

      {Object.keys(r.interpretations).length > 0 && (
        <Card title={t("interpretations")}>
          <div className="grid md:grid-cols-2 gap-3">
            {Object.entries(r.interpretations).map(([k, v]) => (
              <div key={k} className="border border-line rounded-md p-3 text-sm">
                <div className="label mb-1">{tk("interp_", k)}</div>
                {v.status && <StatusBadge code={v.status} />}
                {v.eligible_from && <p className="text-xs text-muted">{t("eligibleFrom")} {fd(v.eligible_from)}</p>}
                {v.projected_date && <p className="text-xs text-muted">{t("projected")} {fd(v.projected_date)}</p>}
                {v.ceiling_date && <p className="text-xs text-muted">{t("ceilingDate", { date: fd(v.ceiling_date) })}</p>}
                {v.summary && <Recorded text={v.summary} />}
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card title={t("charges")}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left"><tr className="text-muted">
              <th className="py-1 pr-3">{t("charge")}</th><th className="py-1 pr-3">{t("maximum")}</th>
              <th className="py-1 pr-3">{t("threshold")}</th><th className="py-1 pr-3">{t("legalDataCol")}</th></tr></thead>
            <tbody>
              {r.charge_calcs.map((c) => {
                const rec = detail.charges.find((x) => `${x.act} ${x.section}` === c.charge.split(" (")[0])?.record;
                return (
                  <tr key={c.charge} className="border-t border-line align-top">
                    <td className="py-1.5 pr-3 font-medium">{c.charge}{rec && <div className="text-xs text-muted" lang="en">{rec.title}</div>}</td>
                    <td className="py-1.5 pr-3">{fterm(c.max_term)}{c.max_days ? ` (${c.max_days} ${t("dayUnit")})` : ""}</td>
                    <td className="py-1.5 pr-3">{c.threshold_days ?? "—"}</td>
                    <td className="py-1.5 pr-3 text-xs">
                      {c.unverified.length > 0
                        ? <span className="text-review font-semibold">⚠ {t("needsLegalVerification")}</span>
                        : rec?.verified_by?.startsWith("DEMO") ? <span className="text-urgent">{t("demoVerifiedOnly")}</span>
                        : <span className="text-ok">{t("legalVerified")}</span>}
                      {c.special_law && <div className="text-urgent">{t("specialLaw")}</div>}
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
            {r.flags.map((f, i) => (
              <li key={i} className="text-sm">
                <div className="flex gap-2 items-start"><Severity level={f.severity} /><span>{ts(f.code)}</span></div>
                <Recorded text={f.message} />
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title={t("trace")}>
        <p className="text-xs text-muted mb-2">{t("traceNote")}</p>
        <ol lang="en" className="space-y-2 text-sm list-decimal pl-5">
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
