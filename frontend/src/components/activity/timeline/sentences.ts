/**
 * Client sentence templates + reason_code lexicon for the Activity timeline.
 *
 * Producers write data, never prose (Activity Center ADR §4). Unmapped reason
 * codes degrade to a generic phrase — never a snake_case token as the primary
 * line (#427).
 */

import type { Story, TimelineEvent } from "./types";

const REASON_LEXICON: Record<string, string> = {
  downloader_unreachable: "downloader unreachable",
  no_acquisition_route: "no complete acquisition route is ready",
  provider_error: "provider returned an error",
  disk_full: "not enough space on the destination volume",
  checksum_mismatch: "the downloaded file failed its integrity check",
  unmatched_series: "couldn't match the file to a series",
  ambiguous_issue: "more than one issue matches this file",
  bad_archive: "the archive wouldn't open",
  missing_metadata: "the file carries no usable metadata",
  path_conflict: "a file already exists at the destination",
  ignored_by_operator: "you ignored this",
  search_lock_held: "another search was already running",
  download_failed: "the download failed",
  import_failed: "import failed",
};

const UNMAPPED_REASON_PHRASE = "something went wrong";

/**
 * Lexicon lookup. Unmapped codes return a generic phrase (not the raw token).
 * Pass `includeRaw` via `reasonDetailLine` when the expand/detail line needs
 * the original code.
 */
export function reasonPhrase(code?: string | null): string | null {
  if (!code) return null;
  return REASON_LEXICON[code] ?? UNMAPPED_REASON_PHRASE;
}

/** Secondary detail line: mapped phrase, plus raw token when unmapped. */
export function reasonDetailLine(
  code?: string | null,
  detail?: string | null,
): { phrase: string | null; rawCode: string | null; detail: string | null } {
  if (!code && !detail) {
    return { phrase: null, rawCode: null, detail: null };
  }
  if (!code) {
    return { phrase: null, rawCode: null, detail: detail ?? null };
  }
  const mapped = REASON_LEXICON[code];
  if (mapped) {
    return { phrase: mapped, rawCode: null, detail: detail ?? null };
  }
  return {
    phrase: UNMAPPED_REASON_PHRASE,
    rawCode: code,
    detail: detail ?? null,
  };
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * Run-scoped search sentences carry counts when present; a fruitless sweep
 * still says how many it looked at (#432 anti-silence).
 */
function runSentence(event: TimelineEvent): string {
  const c = event.counts;
  if (event.status === "started") {
    if (!c || c.accepted === 0) return "Nothing to search";
    return `Searching ${plural(c.accepted, "wanted issue", "wanted issues")}`;
  }
  if (event.status === "succeeded") {
    if (!c) return "Search finished";
    const parts: string[] = [];
    if (c.grabbed > 0) parts.push(`grabbed ${c.grabbed}`);
    if (c.no_match > 0) parts.push(`no results for ${c.no_match}`);
    if (c.failed > 0) parts.push(`${c.failed} failed`);
    const tail = parts.length > 0 ? ` — ${parts.join(", ")}` : "";
    return `Searched ${plural(c.accepted, "wanted issue", "wanted issues")}${tail}`;
  }
  if (event.status === "blocked") return "Search blocked";
  if (event.status === "cancelled") return "Search stopped";
  if (event.status === "no_match") return "Search found nothing";
  if (event.status === "failed") return "Couldn't finish search";
  return "Search finished";
}

/**
 * Voice rule (#426): Comicarr is the implicit subject; failures read
 * "Couldn't ⟨verb⟩", never "⟨Noun⟩ failed".
 */
export function sentenceFor(event: TimelineEvent): string {
  const label = event.subject_label;

  if (event.subject_type === "run") return runSentence(event);

  switch (`${event.activity}.${event.status}`) {
    case "search.no_match":
      return `No results for ${label}`;
    case "search.failed":
    case "search.blocked":
      return `Couldn't search for ${label}`;
    case "search.needs_attention":
      return `${label} needs attention`;
    case "search.cancelled":
      return `Stopped searching for ${label}`;
    case "search.started":
      return `Searching for ${label}`;
    case "search.succeeded":
      return `Searched for ${label}`;

    case "grab.succeeded":
      return event.provider
        ? `Grabbed ${label} from ${event.provider}`
        : `Grabbed ${label}`;
    case "grab.failed":
      return `Couldn't grab ${label}`;
    case "grab.blocked":
      return `Couldn't send ${label} to the downloader`;
    case "grab.cancelled":
      return `Stopped grabbing ${label}`;

    case "download.succeeded":
      return `Downloaded ${label}`;
    case "download.failed":
      return `Couldn't download ${label}`;
    case "download.cancelled":
      return `Stopped downloading ${label}`;

    case "import.started":
      return `Importing ${label}`;
    case "import.succeeded":
      return `Imported ${label}`;
    case "import.failed":
      return `Couldn't import ${label}`;
    case "import.needs_attention":
      return `Stopped on ${label} — needs your decision`;
    case "import.cancelled":
      return `Stopped importing ${label}`;

    case "tag.started":
      return `Tagging ${label}`;
    case "tag.succeeded":
      return `Tagged ${label}`;
    case "tag.failed":
      return `Couldn't tag ${label}`;
    case "tag.needs_attention":
      return `Tagging stopped on ${label} — needs your decision`;

    case "refresh.succeeded":
      return event.counts?.accepted
        ? `Refreshed ${label} — ${plural(event.counts.accepted, "new issue", "new issues")}`
        : `Refreshed ${label}`;
    case "refresh.failed":
      return `Couldn't refresh ${label}`;
    case "refresh.started":
      return `Refreshing ${label}`;

    case "add.succeeded":
      return event.subject_type === "arc"
        ? `Added story arc ${label}${event.counts ? ` — ${plural(event.counts.accepted, "issue", "issues")}` : ""}`
        : `Added ${label}${event.counts ? ` — ${plural(event.counts.accepted, "issue", "issues")}` : ""}`;
    case "add.failed":
      return `Couldn't add ${label}`;
    case "add.started":
      return `Adding ${label}`;

    default:
      return `${label} — ${event.activity} ${event.status}`;
  }
}

/**
 * Header while open uses the furthest advance sentence; once closed, the
 * closer's own sentence (Activity Center ADR §5). Live journal stage is out
 * of scope for this ticket (status indicator owns derived open-work).
 */
export function storyHeadline(story: Story): string {
  if (story.closer) return sentenceFor(story.closer);
  const last = story.events[story.events.length - 1];
  return last ? sentenceFor(last) : story.subject_label;
}

/** Determinate per-run progress when counts are present; never a percentage. */
export function runProgress(story: Story): string | null {
  if (story.closer || story.subject_type !== "run") return null;
  const counts = story.events[0]?.counts;
  if (!counts || counts.resolved == null) return null;
  return `${counts.resolved} of ${counts.accepted} resolved`;
}
