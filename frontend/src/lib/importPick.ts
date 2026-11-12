import type { ImportCandidate, ImportPickPanel } from "@/types";

/** "1.4 GB", "248 MB", "12 KB". Decimal units, as file managers show them. */
export function formatBytes(bytes: number | null | undefined): string | null {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return null;
  if (bytes < 1000) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1000;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const digits = value >= 10 || unit < 2 ? 0 : 1;
  return `${value.toFixed(digits)} ${units[unit]}`;
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
    parts.push(`${candidate.issues} issue${candidate.issues === 1 ? "" : "s"}`);
  }
  parts.push(candidate.in_library ? "in library" : "not in library");
  return parts.join(" · ");
}

/** Why the group is waiting, in a sentence, plus what the panel did about it. */
export function pickNote(panel: ImportPickPanel): string {
  const best = panel.candidates[0]?.score ?? 0;
  let why: string;
  switch (panel.reason) {
    case "remembered":
      why = `You matched this folder to ${
        panel.remembered?.comic_name || "a series"
      } before, so that pick is selected.`;
      break;
    case "tied":
      why = `${
        panel.tied === 2 ? "Two series" : `${panel.tied} series`
      } in your library share this title, so this one needs a check.`;
      break;
    case "mixed_years":
      why = `The files name more than one year (${panel.years.join(", ")}), so they may not be one series.`;
      break;
    case "below_bar":
      why = `The best guess scored ${best}%, under your ${panel.confidence_bar}% auto-import bar.`;
      break;
    case "confident":
      why = `This match clears your ${panel.confidence_bar}% auto-import bar.`;
      break;
    default:
      why = "Nothing in your library looks like this.";
  }
  const extras: string[] = [];
  if (panel.pick && panel.reason !== "remembered") {
    extras.push("Comicarr's pick is selected");
  }
  if (panel.remembers && panel.reason !== "remembered") {
    extras.push("your choice is remembered for future files from this folder");
  }
  if (!extras.length) return why;
  const tail = extras.join("; ");
  return `${why} ${tail[0].toUpperCase()}${tail.slice(1)}.`;
}
