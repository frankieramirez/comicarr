import { ph, plural, t } from "@lingui/core/macro";
/**
 * Client sentence templates + reason_code lexicon for the Activity timeline.
 *
 * Producers write data, never prose (Activity Center ADR §4). Unmapped reason
 * codes degrade to a generic phrase — never a snake_case token as the primary
 * line (#427).
 */

import type { RunCounts, Story, TimelineEvent } from "./types";

const REASON_LEXICON = (): Record<string, string> => ({
  downloader_unreachable: t`downloader unreachable`,
  no_acquisition_route: t`no complete acquisition route is ready`,
  provider_error: t`provider returned an error`,
  disk_full: t`not enough space on the destination volume`,
  checksum_mismatch: t`the downloaded file failed its integrity check`,
  unmatched_series: t`couldn't match the file to a series`,
  ambiguous_issue: t`more than one issue matches this file`,
  bad_archive: t`the archive wouldn't open`,
  missing_metadata: t`the file carries no usable metadata`,
  path_conflict: t`a file already exists at the destination`,
  ignored_by_operator: t`you ignored this`,
  search_lock_held: t`another search was already running`,
  download_failed: t`the download failed`,
  import_failed: t`import failed`,
});

const UNMAPPED_REASON_PHRASE = "something went wrong";

/**
 * Lexicon lookup. Unmapped codes return a generic phrase (not the raw token).
 * Pass `includeRaw` via `reasonDetailLine` when the expand/detail line needs
 * the original code.
 */
export function reasonPhrase(code?: string | null): string | null {
  if (!code) return null;
  return REASON_LEXICON()[code] ?? UNMAPPED_REASON_PHRASE;
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
  const mapped = REASON_LEXICON()[code];
  if (mapped) {
    return { phrase: mapped, rawCode: null, detail: detail ?? null };
  }
  return {
    phrase: UNMAPPED_REASON_PHRASE,
    rawCode: code,
    detail: detail ?? null,
  };
}

/**
 * Run counts: the envelope field when present, else the JSON producers put in
 * `reason_detail` for run rows.
 */
export function countsOf(event: TimelineEvent): RunCounts | null {
  if (event.counts) return event.counts;
  if (event.subject_type !== "run" || !event.reason_detail) return null;
  try {
    const parsed: unknown = JSON.parse(event.reason_detail);
    if (parsed && typeof parsed === "object" && "accepted" in parsed) {
      const c = parsed as Partial<RunCounts>;
      return {
        accepted: Number(c.accepted) || 0,
        grabbed: Number(c.grabbed) || 0,
        no_match: Number(c.no_match) || 0,
        failed: Number(c.failed) || 0,
      };
    }
  } catch {
    // Not JSON: an older row or a free-text detail.
  }
  return null;
}

/**
 * Run-scoped search sentences carry counts when present; a fruitless sweep
 * still says how many it looked at (#432 anti-silence).
 */
function runSentence(event: TimelineEvent): string {
  const c = countsOf(event);
  if (event.status === "started") {
    if (!c || c.accepted === 0) return t`Nothing to search`;
    return plural(c.accepted, {
      one: "Searching # wanted issue",
      other: "Searching # wanted issues",
    });
  }
  if (event.status === "succeeded") {
    if (!c) return t`Search finished`;
    const parts: string[] = [];
    if (c.grabbed > 0) parts.push(t`grabbed ${ph({ count: c.grabbed })}`);
    if (c.no_match > 0)
      parts.push(t`no results for ${ph({ count: c.no_match })}`);
    if (c.failed > 0) parts.push(t`${ph({ count: c.failed })} failed`);
    if (parts.length === 0) {
      return plural(c.accepted, {
        one: "Searched # wanted issue",
        other: "Searched # wanted issues",
      });
    }
    const details = parts.join(", ");
    return plural(c.accepted, {
      one: `Searched # wanted issue — ${details}`,
      other: `Searched # wanted issues — ${details}`,
    });
  }
  if (event.status === "blocked") return t`Search blocked`;
  if (event.status === "cancelled") return t`Search stopped`;
  if (event.status === "no_match") return t`Search found nothing`;
  if (event.status === "failed") return t`Couldn't finish search`;
  return t`Search finished`;
}

const ACTOR_LABELS = (): Record<string, string> => ({
  mcp: t`via MCP`,
});

/** "via MCP" when an agent asked for the change; null for Comicarr's own work. */
export function actorLabel(event: TimelineEvent): string | null {
  if (!event.actor) return null;
  const actor = event.actor;
  return ACTOR_LABELS()[actor] ?? t`via ${actor}`;
}

/** An operator-requested status change; `reason_detail` carries the new status. */
function statusChangeSentence(event: TimelineEvent): string {
  const label = event.subject_label;
  const status = event.reason_detail;
  if (event.subject_type === "series") {
    if (status === "Paused") return t`Paused ${label}`;
    if (status === "Active") return t`Resumed ${label}`;
  } else {
    if (status === "Wanted") return t`Marked ${label} wanted`;
    if (status === "Skipped") return t`Marked ${label} skipped`;
  }
  return status ? t`Set ${label} to ${status}` : t`Changed ${label}`;
}

/**
 * Voice rule (#426): Comicarr is the implicit subject; failures read
 * "Couldn't ⟨verb⟩", never "⟨Noun⟩ failed".
 */
export function sentenceFor(event: TimelineEvent): string {
  const label = event.subject_label;

  if (event.subject_type === "run") return runSentence(event);
  if (event.activity === "status_change") return statusChangeSentence(event);

  switch (`${event.activity}.${event.status}`) {
    case "search.no_match":
      return t`No results for ${label}`;
    case "search.failed":
    case "search.blocked":
      return t`Couldn't search for ${label}`;
    case "search.needs_attention":
      return t`${label} needs attention`;
    case "search.cancelled":
      return t`Stopped searching for ${label}`;
    case "search.started":
      return t`Searching for ${label}`;
    case "search.succeeded":
      return t`Searched for ${label}`;

    case "grab.succeeded":
      return event.provider
        ? t`Grabbed ${label} from ${ph({ provider: event.provider })}`
        : t`Grabbed ${label}`;
    case "grab.failed":
      return t`Couldn't grab ${label}`;
    case "grab.blocked":
      return t`Couldn't send ${label} to the downloader`;
    case "grab.cancelled":
      return t`Stopped grabbing ${label}`;

    case "download.succeeded":
      return t`Downloaded ${label}`;
    case "download.failed":
      return t`Couldn't download ${label}`;
    case "download.cancelled":
      return t`Stopped downloading ${label}`;

    case "import.started":
      return t`Importing ${label}`;
    case "import.succeeded":
      return t`Imported ${label}`;
    case "import.failed":
      return t`Couldn't import ${label}`;
    case "import.needs_attention":
      return t`Stopped on ${label} — needs your decision`;
    case "import.cancelled":
      return t`Stopped importing ${label}`;

    case "tag.started":
      return t`Tagging ${label}`;
    case "tag.succeeded":
      return t`Tagged ${label}`;
    case "tag.failed":
      return t`Couldn't tag ${label}`;
    case "tag.needs_attention":
      return t`Tagging stopped on ${label} — needs your decision`;

    case "refresh.succeeded":
      return event.counts?.accepted
        ? plural(event.counts.accepted, {
            one: `Refreshed ${label} — # new issue`,
            other: `Refreshed ${label} — # new issues`,
          })
        : t`Refreshed ${label}`;
    case "refresh.failed":
      return t`Couldn't refresh ${label}`;
    case "refresh.started":
      return t`Refreshing ${label}`;

    case "add.succeeded": {
      const added = event.counts?.accepted;
      if (event.subject_type === "arc") {
        return added == null
          ? t`Added story arc ${label}`
          : plural(added, {
              one: `Added story arc ${label} — # issue`,
              other: `Added story arc ${label} — # issues`,
            });
      }
      return added == null
        ? t`Added ${label}`
        : plural(added, {
            one: `Added ${label} — # issue`,
            other: `Added ${label} — # issues`,
          });
    }
    case "add.failed":
      return t`Couldn't add ${label}`;
    case "add.started":
      return t`Adding ${label}`;

    default:
      return t`${label} — ${ph({ activity: event.activity })} ${ph({ status: event.status })}`;
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
  return t`${ph({ resolved: counts.resolved })} of ${ph({ total: counts.accepted })} resolved`;
}
