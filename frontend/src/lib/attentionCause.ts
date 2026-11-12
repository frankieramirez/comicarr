import type { AttentionCause } from "@/components/activity/timeline";

/**
 * Copy for a "Needs you" cause row (v2 dashboard). Pure, no React: the server
 * folds series into causes; this only phrases what it sent.
 */

export function plural(n: number, word: string) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** "A", "A and B", "A, B and C", "A, B and 3 more series". */
export function seriesList(labels: string[]): string {
  if (labels.length <= 1) return labels[0] ?? "";
  if (labels.length <= 3) {
    return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
  }
  return `${labels.slice(0, 2).join(", ")} and ${labels.length - 2} more series`;
}

/** The sentence under a cause's headline: what it touches, then what fixes it. */
export function causeSubline(cause: AttentionCause): string {
  const labels = cause.series.map((series) => series.series_label);
  let where: string;
  if (cause.member_count === 1) {
    where = cause.series[0]?.issue_labels[0] ?? labels[0] ?? "";
  } else if (cause.series.length === 1) {
    where = `${plural(cause.member_count, "issue")} in ${labels[0]}`;
  } else if (
    cause.series.every((s) => s.member_count === cause.series[0].member_count)
  ) {
    where = `${seriesList(labels)}, ${cause.series[0].member_count} ${
      cause.series[0].member_count === 1 ? "issue" : "issues"
    } each`;
  } else {
    where = `${plural(cause.member_count, "issue")} in ${seriesList(labels)}`;
  }
  return cause.hint ? `${where}. ${cause.hint}` : `${where}.`;
}
