import { plural, t } from "@lingui/core/macro";
import type { AttentionCause } from "@/components/activity/timeline";

/**
 * Copy for a "Needs you" cause row (v2 dashboard). Pure, no React: the server
 * folds series into causes; this only phrases what it sent.
 */

/** English-only count for callers not yet localized; prefer the `plural` macro. */
export function countNoun(n: number, word: string) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** "A", "A and B", "A, B and C", "A, B and 3 more series". */
export function seriesList(labels: string[]): string {
  const [first = "", second = "", third = ""] = labels;
  if (labels.length <= 1) return first;
  if (labels.length === 2) return t`${first} and ${second}`;
  if (labels.length === 3) return t`${first}, ${second} and ${third}`;
  const rest = labels.length - 2;
  return plural(rest, {
    one: `${first}, ${second} and # more series`,
    other: `${first}, ${second} and # more series`,
  });
}

/** The sentence under a cause's headline: what it touches, then what fixes it. */
export function causeSubline(cause: AttentionCause): string {
  const labels = cause.series.map((series) => series.series_label);
  let where: string;
  if (cause.member_count === 1) {
    where = cause.series[0]?.issue_labels[0] ?? labels[0] ?? "";
  } else if (cause.series.length === 1) {
    const series = labels[0] ?? "";
    where = plural(cause.member_count, {
      one: `# issue in ${series}`,
      other: `# issues in ${series}`,
    });
  } else if (
    cause.series.every((s) => s.member_count === cause.series[0].member_count)
  ) {
    const list = seriesList(labels);
    where = plural(cause.series[0].member_count, {
      one: `${list}, # issue each`,
      other: `${list}, # issues each`,
    });
  } else {
    const list = seriesList(labels);
    where = plural(cause.member_count, {
      one: `# issue in ${list}`,
      other: `# issues in ${list}`,
    });
  }
  const hint = cause.hint;
  return hint ? t`${where}. ${hint}` : t`${where}.`;
}
