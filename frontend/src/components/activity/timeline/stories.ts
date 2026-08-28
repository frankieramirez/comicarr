/**
 * Story grouping for the Activity timeline (#428 / Activity Center ADR §5).
 *
 * Rules:
 *  - identity is `(subject_type, subject_id)`, never `release_key`
 *  - opened by an advance; closed by the terminal-pair allowlist
 *  - always collapsed; a group of one degenerates to a plain row
 *  - position is the opening row's `created_at`; nothing re-sorts
 *  - a retry opens a second story, never reopening the first
 *
 * Run-scoped search: `search.started @ run` is treated as an opener so a
 * started/succeeded pair does not render as two unrelated rows (prototype
 * extension kept for production readability).
 */

import type { FeedNode, Story, TimelineEvent } from "./types";
import { severityOf } from "./types";

/** Issue/annual/series advances that open or extend a multi-event story. */
const ISSUE_ADVANCES = new Set([
  "grab.succeeded",
  "download.succeeded",
  "import.started",
  "tag.started",
]);

/**
 * Normative terminal-pair allowlist (Activity Center ADR §5).
 * Terminality is a function of the `(activity, status)` pair.
 */
const ISSUE_TERMINALS = new Set([
  "grab.failed",
  "grab.blocked",
  "grab.cancelled",
  "download.failed",
  "download.cancelled",
  "import.succeeded",
  "import.failed",
  "import.needs_attention",
  "import.cancelled",
  "tag.succeeded",
  "tag.failed",
  "tag.needs_attention",
]);

const RUN_TERMINALS = new Set([
  "search.succeeded",
  "search.failed",
  "search.blocked",
  "search.cancelled",
  "search.no_match",
]);

function cellOf(event: TimelineEvent): string {
  return `${event.activity}.${event.status}`;
}

function isAdvance(event: TimelineEvent): boolean {
  if (event.subject_type === "run") {
    return cellOf(event) === "search.started";
  }
  return ISSUE_ADVANCES.has(cellOf(event));
}

function isTerminal(event: TimelineEvent): boolean {
  if (event.subject_type === "run") {
    return RUN_TERMINALS.has(cellOf(event));
  }
  if (ISSUE_TERMINALS.has(cellOf(event))) return true;
  return severityOf(String(event.status)) === "action_required";
}

function subjectKey(event: TimelineEvent): string {
  return `${event.subject_type}:${event.subject_id}`;
}

/**
 * Group a page of narrative events into always-collapsed stories.
 * Events may arrive newest-first from the API; processing is chronological.
 */
export function buildFeed(events: TimelineEvent[]): FeedNode[] {
  const ascending = [...events].sort((a, b) => {
    if (a.created_at < b.created_at) return -1;
    if (a.created_at > b.created_at) return 1;
    return String(a.event_id).localeCompare(String(b.event_id), undefined, {
      numeric: true,
    });
  });

  const open = new Map<string, Story>();
  const nodes: Story[] = [];

  for (const event of ascending) {
    const key = subjectKey(event);
    const current = open.get(key);

    if (current) {
      current.events.push(event);
      if (isTerminal(event)) {
        current.closer = event;
        open.delete(key);
      }
      continue;
    }

    const story: Story = {
      key: `${key}@${event.created_at}@${event.event_id}`,
      subject_type: String(event.subject_type),
      subject_id: String(event.subject_id),
      subject_label: event.subject_label,
      parent_series_id: event.parent_series_id,
      opened_at: event.created_at,
      events: [event],
      closer: null,
    };

    if (isAdvance(event)) {
      open.set(key, story);
      nodes.push(story);
      continue;
    }

    story.closer = event;
    nodes.push(story);
  }

  return nodes.sort((a, b) => {
    if (a.opened_at < b.opened_at) return 1;
    if (a.opened_at > b.opened_at) return -1;
    return b.key.localeCompare(a.key);
  });
}

export function storyHasTrouble(story: Story): boolean {
  const closer = story.closer;
  if (!closer) return false;
  return severityOf(String(closer.status)) === "action_required";
}

export function isOpen(story: Story): boolean {
  return story.closer === null;
}

/** Local calendar day key for sticky day rules. */
export function dayKey(iso: string): string {
  const date = parseTimelineDate(iso);
  if (!date) return iso;
  return date.toDateString();
}

export function dayLabel(iso: string, now: Date = new Date()): string {
  const date = parseTimelineDate(iso);
  if (!date) return iso;

  const today = new Date(now);
  const yesterday = new Date(now);
  yesterday.setDate(today.getDate() - 1);

  if (date.toDateString() === today.toDateString()) return "TODAY";
  if (date.toDateString() === yesterday.toDateString()) return "YESTERDAY";
  return date
    .toLocaleDateString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
    })
    .toUpperCase();
}

export function clockOf(iso: string): string {
  const date = parseTimelineDate(iso);
  if (!date) return "—";
  return date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/** Accept both ISO and SQLite-style `YYYY-MM-DD HH:MM:SS` timestamps. */
export function parseTimelineDate(value: string): Date | null {
  if (!value) return null;
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Deep-link for a subject when enough identity remains. */
export function subjectHref(story: {
  subject_type: string;
  subject_id: string;
  parent_series_id?: string | null;
}): string | null {
  const id = story.subject_id;
  if (!id) return null;
  switch (story.subject_type) {
    case "series":
      return `/library/${encodeURIComponent(id)}`;
    case "issue":
    case "annual": {
      const seriesId = story.parent_series_id;
      if (!seriesId) return null;
      return `/library/${encodeURIComponent(seriesId)}/issue/${encodeURIComponent(id)}`;
    }
    case "arc":
      return `/story-arcs/${encodeURIComponent(id)}`;
    default:
      return null;
  }
}
