/** NyayaSetu mark: a bridge (setu) — an arch over two pillars — drawn in currentColor. */
export function Logo({ className = "h-9 w-9" }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" className={className} aria-hidden="true" fill="none" stroke="currentColor" strokeWidth={2.4}
      strokeLinecap="round" strokeLinejoin="round">
      <rect x="1.5" y="1.5" width="37" height="37" rx="9" strokeWidth={1.6} opacity={0.35} />
      <path d="M7 27 Q20 9 33 27" />
      <path d="M5 27 H35" />
      <path d="M12 27 V20.5 M20 27 V16 M28 27 V20.5" strokeWidth={1.8} />
      <path d="M9 32 H31" strokeWidth={1.8} opacity={0.6} />
    </svg>
  );
}
