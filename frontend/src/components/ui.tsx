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
  if (code === "DEFAULT_BAIL_REVIEW") return "REVIEW";
  if (code.startsWith("URGENT") || code.startsWith("DEFAULT_BAIL_WINDOW") || code === "DEFAULT_BAIL_RIGHT_ASSERTED") return "URGENT";
  if (code === "ELIGIBLE") return "ELIGIBLE";
  if (code.startsWith("REVIEW")) return "REVIEW";
  return "NEUTRAL";
}

export function StatusBadge({ code, className = "" }: { code: string | null | undefined; className?: string }) {
  const { ts } = useI18n();
  if (!code) return <span className="text-muted">—</span>;
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold ${TONE[tone(code)]} ${className}`}>
      {ts(code)}
    </span>
  );
}

export function Severity({ level }: { level: string }) {
  const { tk } = useI18n();
  const map: Record<string, string> = { critical: TONE.CRITICAL, high: TONE.URGENT, medium: TONE.REVIEW, low: TONE.NEUTRAL,
    warning: TONE.REVIEW, info: TONE.NEUTRAL };
  return <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[11px] font-semibold ${map[level] ?? TONE.NEUTRAL}`}>{tk("sev_", level)}</span>;
}

export function DemoBadge({ label }: { label?: string | null }) {
  const { t } = useI18n();
  if (!label) return null;
  // the label names the demo case ("DEMO A — not eligible"); the badge word itself is translated
  return <span title={label} className="ml-1 inline-flex rounded border border-accent/40 bg-urgent-bg px-1.5 py-0.5 text-[11px] font-bold text-accent">{t("demoCase")} {label.split(" ")[1] ?? ""}</span>;
}

export function Card({ title, children, actions, className = "" }: { title?: ReactNode; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={`card p-4 ${className}`}>
      {(title || actions) && (
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
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
    <div className="min-w-0">
      <div className="label break-words">{label}</div>
      <div className="text-2xl font-bold tabular-nums">{value}</div>
      {sub && <div className="text-xs text-muted break-words">{sub}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return <div role="alert" className="card border-critical/40 bg-critical-bg text-critical p-3 text-sm mb-4">{error}</div>;
}

export function Notice({ text, tone: tn = "ok" }: { text: string | null; tone?: "ok" | "urgent" }) {
  if (!text) return null;
  return <p role="status" className={`card p-3 text-sm mb-3 ${tn === "ok" ? "bg-ok-bg text-ok" : "bg-urgent-bg text-urgent"}`}>{text}</p>;
}

export function Loading() {
  const { t } = useI18n();
  return <p role="status" className="text-muted py-8">{t("loading")}</p>;
}

/** A small labelled form field. */
export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block text-sm min-w-0">
      <span className="label block mb-1 break-words">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted mt-0.5">{hint}</span>}
    </label>
  );
}

export const inputCls = "w-full border border-line rounded-md px-2.5 py-1.5 bg-surface text-sm";
