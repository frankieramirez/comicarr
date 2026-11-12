interface ConfidenceBadgeProps {
  confidence: number | null;
  showLabel?: boolean;
}

/**
 * Match confidence as a short meter plus its number. The bar carries the
 * reading; color only separates a strong guess from one worth checking.
 */
export default function ConfidenceBadge({
  confidence,
  showLabel = true,
}: ConfidenceBadgeProps) {
  if (confidence === null || confidence === undefined) {
    return <span className="mono-meta">{showLabel ? "Unknown" : "?"}</span>;
  }

  const pct = Math.max(0, Math.min(100, confidence));
  const tone =
    pct >= 80
      ? "var(--status-active)"
      : pct >= 50
        ? "var(--foreground-2)"
        : "var(--status-paused)";

  return (
    <span
      className="inline-flex items-center gap-2"
      title={`${pct}% match confidence`}
    >
      <span
        aria-hidden="true"
        className="relative h-1 w-10 overflow-hidden rounded-full bg-surface-3"
      >
        <span
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${pct}%`, background: tone }}
        />
      </span>
      <span className="font-mono text-[11px] tabular-nums text-foreground-2">
        {showLabel ? `${confidence}%` : confidence}
      </span>
    </span>
  );
}
