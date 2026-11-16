import { ph, plural, t } from "@lingui/core/macro";
import type { ImportCandidate, ImportPickPanel } from "@/types";
import { formatNumber } from "@/lib/intl";

/** "1.4 GB", "248 MB", "12 KB". Decimal units, as file managers show them. */
export function formatBytes(bytes: number | null | undefined): string | null {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return null;
  if (bytes < 1000) return t`${ph({ size: formatNumber(bytes) })} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1000;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const digits = value >= 10 || unit < 2 ? 0 : 1;
  const size = formatNumber(value, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  const symbol = units[unit];
  return `${size} ${symbol}`;
}

/**
 * Library candidates first, then provider ones the library does not already
 * hold, best score first. A provider hit for a series already in the library
 * is the same series, so it is dropped rather than listed twice.
 */
export function mergeCandidates(
  library: ImportCandidate[],
  remote: ImportCandidate[] = [],
  limit = 3,
): ImportCandidate[] {
  const seen = new Set(library.map((candidate) => candidate.comic_id));
  const extra = remote.filter(
    (candidate) => !candidate.in_library && !seen.has(candidate.comic_id),
  );
  const pinned = library.slice(0, limit);
  const rest = [...library.slice(limit), ...extra].sort(
    (a, b) => b.score - a.score,
  );
  return [...pinned, ...rest]
    .sort((a, b) => b.score - a.score)
    .slice(0, Math.max(limit, pinned.length));
}

/** Whether the library alone leaves the pick thin enough to ask a provider. */
export function wantsProviderSearch(panel: ImportPickPanel): boolean {
  if (panel.reason === "remembered") return false;
  const best = panel.candidates[0]?.score ?? 0;
  return panel.candidates.length < 3 || best < panel.confidence_bar;
}

export function candidateTitle(candidate: ImportCandidate): string {
  return candidate.year
    ? `${candidate.name} (${candidate.year})`
    : candidate.name;
}

export function candidateMeta(candidate: ImportCandidate): string {
  const parts: string[] = [];
  if (candidate.publisher) parts.push(candidate.publisher);
  if (candidate.issues != null) {
    parts.push(plural(candidate.issues, { one: "# issue", other: "# issues" }));
  }
  parts.push(candidate.in_library ? t`in library` : t`not in library`);
  return parts.join(" · ");
}

/** Why the group is waiting, in a sentence, plus what the panel did about it. */
export function pickNote(panel: ImportPickPanel): string {
  const best = panel.candidates[0]?.score ?? 0;
  let why: string;
  switch (panel.reason) {
    case "remembered":
      why = panel.remembered?.comic_name
        ? t`You matched this folder to ${ph({ series: panel.remembered.comic_name })} before, so that pick is selected.`
        : t`You matched this folder to a series before, so that pick is selected.`;
      break;
    case "tied":
      why =
        panel.tied === 2
          ? t`Two series in your library share this title, so this one needs a check.`
          : t`${ph({ count: panel.tied })} series in your library share this title, so this one needs a check.`;
      break;
    case "mixed_years":
      why = t`The files name more than one year (${ph({ years: panel.years.join(", ") })}), so they may not be one series.`;
      break;
    case "other_year": {
      const top = panel.candidates[0];
      const years = panel.years.join(", ");
      why =
        top && top.year
          ? t`The files name ${years}, but ${ph({ series: candidateTitle(top) })} started in ${ph({ year: top.year })}. Files often carry the issue's cover year, so check it's the right volume.`
          : t`The files name ${years}, but the closest series started in another year. Files often carry the issue's cover year, so check it's the right volume.`;
      break;
    }
    case "below_bar":
      why = t`The best guess scored ${best}%, under your ${ph({ confidence_bar: panel.confidence_bar })}% auto-import bar.`;
      break;
    case "confident":
      why = t`This match clears your ${ph({ confidence_bar: panel.confidence_bar })}% auto-import bar.`;
      break;
    default:
      why = t`Nothing in your library looks like this.`;
  }
  const picked = Boolean(panel.pick) && panel.reason !== "remembered";
  const remembers = Boolean(panel.remembers) && panel.reason !== "remembered";
  if (picked && remembers) {
    return t`${why} Comicarr's pick is selected; your choice is remembered for future files from this folder.`;
  }
  if (picked) return t`${why} Comicarr's pick is selected.`;
  if (remembers) {
    return t`${why} Your choice is remembered for future files from this folder.`;
  }
  return why;
}
