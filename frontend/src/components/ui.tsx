"use client";

import type { ReactNode } from "react";
import { useI18n } from "@/lib/i18n";

const TONE: Record<string, string> = {
  CRITICAL: "bg-critical-bg text-critical border-critical/30",
  URGENT: "bg-urgent-bg text-urgent border-urgent/30",
  ELIGIBLE: "bg-ok-bg text-ok border-ok/30",
  REVIEW: "bg-review-bg text-review border-review/30",
  NEUTRAL: "bg-neutral-bg text-muted border-line",
};

export function tone(code: string | null | undefined): keyof typeof TONE {
  if (!code) return "NEUTRAL";
  if (code.startsWith("CRITICAL")) return "CRITICAL";
  if (code.startsWith("URGENT") || code.startsWith("DEFAULT_BAIL")) return "URGENT";
  if (code === "ELIGIBLE") return "ELIGIBLE";
  if (code.startsWith("REVIEW")) return "REVIEW";
  return "NEUTRAL";
}

export function StatusBadge({ code, className = "" }: { code: string | null | undefined; className?: string }) {
  const { ts } = useI18n();
  if (!code) return <span className="text-muted">—</span>;
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap ${TONE[tone(code)]} ${className}`}>
      {ts(code)}
    </span>
  );
}

export function Severity({ level }: { level: string }) {
  const map: Record<string, string> = { critical: TONE.CRITICAL, high: TONE.URGENT, medium: TONE.REVIEW, low: TONE.NEUTRAL,
    warning: TONE.REVIEW, info: TONE.NEUTRAL };
  return <span className={`rounded border px-1.5 py-0.5 text-[11px] font-semibold uppercase ${map[level] ?? TONE.NEUTRAL}`}>{level}</span>;
}

export function Card({ title, children, actions, className = "" }: { title?: ReactNode; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={`card p-4 ${className}`}>
      {(title || actions) && (
        <div className="flex items-center justify-between gap-3 mb-3">
          {title && <h2 className="font-semibold text-ink">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div>
      <div className="label">{label}</div>
      <div className="text-2xl font-bold tabular-nums">{value}</div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return <div role="alert" className="card border-critical/40 bg-critical-bg text-critical p-3 text-sm mb-4">{error}</div>;
}

export function Loading() {
  const { t } = useI18n();
  return <p role="status" className="text-muted py-8">{t("loading")}</p>;
}

export function fmtDate(d?: string | null) {
  if (!d) return "—";
  const x = new Date(d.length === 10 ? d + "T00:00:00" : d);
  return x.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}
