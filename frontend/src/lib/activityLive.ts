import { t } from "@lingui/core/macro";
/**
 * Client contract for the single `activity` SSE stream (Activity Center ADR §8).
 *
 * Pure composition — no React, no I/O, no query client. Everything decidable
 * from one payload lives here; `useServerEvents` owns only the socket, the
 * timers and the dispatch.
 *
 * The stream is never read as a list: a payload says *what to refetch* and
 * *whether to interrupt the operator*, never *what to render*.
 */

import { severityOf } from "@/components/activity/timeline/types";
import type { TimelineEvent } from "@/components/activity/timeline/types";
import { sentenceFor } from "@/components/activity/timeline/sentences";
import type { ComicAddedDetail } from "@/types/events";

/** Trailing window that collapses an event burst into one invalidation pass. */
export const ACTIVITY_COALESCE_MS = 250;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Parse an `activity` frame into a narrative row, or null when the frame is
 * unusable. A row without stable identity cannot key anything, so it is
 * dropped rather than half-trusted.
 */
export function parseActivityEvent(
  raw: string | null | undefined,
): TimelineEvent | null {
  if (!raw) return null;
  let decoded: unknown;
  try {
    decoded = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isRecord(decoded)) return null;

  const {
    event_id,
    activity,
    status,
    subject_type,
    subject_id,
    subject_label,
  } = decoded;
  if (event_id === null || event_id === undefined) return null;
  if (typeof activity !== "string" || activity === "") return null;
  if (typeof status !== "string" || status === "") return null;
  if (typeof subject_type !== "string" || subject_type === "") return null;
  if (typeof subject_id !== "string" || subject_id === "") return null;
  if (typeof subject_label !== "string" || subject_label === "") return null;

  return decoded as unknown as TimelineEvent;
}

/**
 * Extra caches a narration stales beyond the activity surfaces — what the
 * retired `addbyid` / `storyarc_added` / generic `message` handlers used to
 * own, now keyed off the one event type instead of their own dead channels.
 *
 * Wanted is included for issue-scoped narration because its sticky annotation
 * is read from the same acquisition ledger the event just moved (ADR §2), and
 * its query has no poll of its own to fall back on.
 */
export function collateralKeys(event: TimelineEvent): string[][] {
  if (event.subject_type === "series") {
    return [["series"], ["series", event.subject_id], ["wanted"]];
  }
  if (event.subject_type === "arc") {
    return [["storyArcs"]];
  }
  if (event.subject_type === "issue" || event.subject_type === "annual") {
    return [["wanted"]];
  }
  return [];
}

/**
 * Detail for the `comic-added` window event the search cards await to settle
 * their add button. Only a *completed* series add resolves a card, so
 * in-progress and non-series narration stays silent.
 */
export function comicAddedDetail(event: TimelineEvent): string | null {
  if (event.activity !== "add" || event.subject_type !== "series") return null;
  if (event.status !== "succeeded" && event.status !== "failed") return null;
  const detail: ComicAddedDetail = {
    comicid: event.subject_id,
    comicname: event.subject_label,
    status: event.status === "succeeded" ? "success" : "failure",
    message: sentenceFor(event),
  };
  return JSON.stringify(detail);
}

export interface TroubleToast {
  title: string;
  description: string;
}

/**
 * Enter-trouble session latch. Trouble interrupts the operator once on the way
 * in; while it stays open the timeline carries the rest.
 */
export interface TroubleLatch {
  latched: boolean;
  /**
   * When the latch closed. Attention counts observed at or before this instant
   * predate the trouble and cannot clear it — the count the client has cached
   * mid-burst is still the pre-trouble one, and treating it as proof of
   * resolution would let the very next event toast again.
   */
  since: number;
}

export const NO_TROUBLE: TroubleLatch = { latched: false, since: 0 };

/**
 * Fold one narration into the latch. `normal` severity never toasts — it is
 * timeline material — and a second `action_required` inside an open trouble
 * session is silent.
 */
export function latchOnEvent(
  latch: TroubleLatch,
  event: TimelineEvent,
  now: number,
): { latch: TroubleLatch; toast: TroubleToast | null } {
  if (severityOf(event.status) !== "action_required") {
    return { latch, toast: null };
  }
  if (latch.latched) {
    return { latch, toast: null };
  }
  return {
    latch: { latched: true, since: now },
    toast: { title: t`Needs attention`, description: sentenceFor(event) },
  };
}

/**
 * Fold an observed attention count into the latch. Open trouble the client can
 * already see arms it — a new failure is not news to an operator staring at
 * `⚠ 3 need attention`. A zero re-arms it, but only when that zero was
 * observed *after* the latch closed; `observedAt` is the query's
 * `dataUpdatedAt`, so a stale cache read cannot unlock it.
 *
 * An unknown count (status query still loading or failed) changes nothing —
 * silence is not evidence of resolution.
 */
export function latchOnAttention(
  latch: TroubleLatch,
  attention: number | undefined,
  observedAt: number,
): TroubleLatch {
  if (attention === undefined) return latch;
  if (attention > 0) {
    return latch.latched ? latch : { latched: true, since: observedAt };
  }
  if (!latch.latched || observedAt <= latch.since) return latch;
  return NO_TROUBLE;
}
