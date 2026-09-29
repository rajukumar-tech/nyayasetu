"use client";

import type { CaseResult, PersonDetail } from "@/lib/api";
import { fmtDate } from "./ui";

const ATTR_COLOR: Record<string, string> = {
  accused: "#b42318", prosecution: "#2c3e6b", court: "#8a6d00", both: "#b54708", other: "#5b6275", unknown: "#9aa0ad",
};

/** Custody intervals (counted), excluded periods and hearings on one time axis. */
export function TimelineChart({ result, detail }: { result: CaseResult; detail: PersonDetail["case_details"][number] }) {
  const tl = result.timeline;
  if (!tl || tl.intervals.length === 0) return <p className="text-sm text-muted">No custody intervals for this case.</p>;
  const dates = [...tl.intervals.flatMap((i) => [i.start, i.end]), ...tl.excluded.flatMap((i) => [i.start, i.end]),
    ...detail.hearings.map((h) => h.date)].map((d) => new Date(d).getTime());
  const min = Math.min(...dates), max = Math.max(...dates);
  const W = 1000, H = 132, pad = 8;
  const x = (d: string) => pad + ((new Date(d).getTime() - min) / Math.max(1, max - min)) * (W - 2 * pad);
  const years: number[] = [];
  for (let y = new Date(min).getFullYear() + 1; y <= new Date(max).getFullYear(); y++) years.push(y);
  const thresholdDate = result.eligible_from_date ?? result.projected_date;
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img"
        aria-label={`Custody timeline: ${tl.intervals.length} counted interval(s), ${result.custody_days} days in custody`}>
        {years.map((y) => {
          const xx = x(`${y}-01-01`);
          return <g key={y}><line x1={xx} x2={xx} y1={10} y2={H - 18} stroke="#dfdcd3" /><text x={xx + 3} y={H - 4} fontSize="11" fill="#5b6275">{y}</text></g>;
        })}
        <text x={pad} y={20} fontSize="11" fill="#5b6275">Custody</text>
        {tl.intervals.map((i, k) => (
          <rect key={k} x={x(i.start)} y={26} width={Math.max(2, x(i.end) - x(i.start))} height={26} rx={3} fill="#2c3e6b">
            <title>{`${fmtDate(i.start)} → ${fmtDate(i.end)}: ${i.explanation}`}</title>
          </rect>
        ))}
        {tl.excluded.map((i, k) => (
          <rect key={`e${k}`} x={x(i.start)} y={26} width={Math.max(2, x(i.end) - x(i.start))} height={26} fill="url(#hatch)" stroke="#b42318">
            <title>{`Excluded ${fmtDate(i.start)} → ${fmtDate(i.end)}: ${i.explanation}`}</title>
          </rect>
        ))}
        <text x={pad} y={72} fontSize="11" fill="#5b6275">Hearings</text>
        {detail.hearings.map((h) => (
          <rect key={h.id} x={x(h.date) - 2} y={78} width={5} height={18} rx={1} fill={ATTR_COLOR[h.attribution] ?? "#9aa0ad"}>
            <title>{`${fmtDate(h.date)} — ${h.reason || "no reason recorded"} (${h.attribution}, ${Math.round(h.confidence * 100)}%)`}</title>
          </rect>
        ))}
        {thresholdDate && (
          <g>
            <line x1={x(thresholdDate)} x2={x(thresholdDate)} y1={14} y2={104} stroke="#067647" strokeWidth={2} strokeDasharray="4 3" />
            <text x={Math.min(x(thresholdDate) + 4, W - 150)} y={112} fontSize="11" fill="#067647">
              {result.eligible_from_date ? "eligible from" : "projected"} {fmtDate(thresholdDate)}
            </text>
          </g>
        )}
        <defs>
          <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="#fef1f0" /><line x1="0" y1="0" x2="0" y2="6" stroke="#b42318" strokeWidth="2" />
          </pattern>
        </defs>
      </svg>
      <figcaption className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted mt-1">
        <span><span className="inline-block w-3 h-3 align-middle rounded-sm bg-navy-2" /> counted custody</span>
        <span><span className="inline-block w-3 h-3 align-middle rounded-sm border border-critical bg-critical-bg" /> excluded (bail / absconding)</span>
        {Object.entries(ATTR_COLOR).map(([k, c]) => (
          <span key={k}><span className="inline-block w-2 h-3 align-middle rounded-sm" style={{ background: c }} /> {k}</span>
        ))}
      </figcaption>
    </figure>
  );
}
