/** Wording for the Wanted pacing banner and per-series ETAs. */

/** "~18 min", "~5 hours", "~14 days" for a duration in hours. */
export function approxDuration(hours: number): string {
  if (hours < 1) {
    const minutes = Math.max(1, Math.round(hours * 60));
    return `~${minutes} min`;
  }
  if (hours < 36) {
    const whole = Math.round(hours);
    return `~${whole} hour${whole === 1 ? "" : "s"}`;
  }
  const days = Math.round(hours / 24);
  return `~${days} day${days === 1 ? "" : "s"}`;
}

/** "in 18 min" until an ISO time, or null when it is unknown or past. */
export function untilLabel(
  iso: string | null | undefined,
  now: number = Date.now(),
): string | null {
  if (!iso) return null;
  const at = new Date(iso).getTime();
  if (Number.isNaN(at)) return null;
  const minutes = Math.round((at - now) / 60_000);
  if (minutes <= 0) return "any moment now";
  if (minutes < 60) return `in ${minutes} min`;
  const hours = Math.round(minutes / 60);
  return `in ${hours} hour${hours === 1 ? "" : "s"}`;
}
