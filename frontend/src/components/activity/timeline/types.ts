/**
 * Activity Center timeline types.
 *
 * Field contract mirrors activity_events / band DTOs (Activity Center ADR).
 * Severity is a pure function of status — never stored.
 */

export type Activity =
  "search" | "grab" | "download" | "import" | "refresh" | "add" | "tag";

/** `retrying` is deliberately absent — #432. */
export type EventStatus =
  | "started"
  | "succeeded"
  | "no_match"
  | "cancelled"
  | "failed"
  | "blocked"
  | "needs_attention";

export type SubjectType = "issue" | "annual" | "series" | "arc" | "run";

export type Severity = "normal" | "action_required";

/** Severity is a pure function of status (#426) — never stored. */
export function severityOf(status: string): Severity {
  return status === "failed" ||
    status === "blocked" ||
    status === "needs_attention"
    ? "action_required"
    : "normal";
}

/** Optional run counts when producers embed them (not a DB column today). */
export interface RunCounts {
  accepted: number;
  grabbed: number;
  no_match: number;
  failed: number;
  /** Present only while the run is open — determinate per-run progress. */
  resolved?: number;
}

export interface TimelineEvent {
  event_id: number | string;
  created_at: string;
  activity: Activity | string;
  status: EventStatus | string;
  subject_type: SubjectType | string;
  subject_id: string;
  /** Denormalized — the timeline must survive deletion of its subject. */
  subject_label: string;
  reason_code?: string | null;
  reason_detail?: string | null;
  provider?: string | null;
  run_id?: string | null;
  release_key?: string | null;
  parent_series_id?: string | null;
  scope_type?: string | null;
  scope_id?: string | null;
  /** Not on the table; optional future/envelope field for run brackets. */
  counts?: RunCounts | null;
}

export type BandStage = "failed" | "manual_review" | "mixed";

/** Operator exits, keyed by the stage that admits them (#525 naming). */
export type BandAction = "retry" | "search_again" | "import" | "stop_wanting";

/**
 * One journal row inside a group. Members carry their own `available_actions`
 * so a mixed-stage group is still workable row by row — the group offers no
 * one-click action, but nothing in it is unreachable.
 */
export interface AttentionMember {
  release_key: string;
  issue_label: string;
  issueid?: string | null;
  stage: BandStage | string;
  available_actions: BandAction[];
  updated_date: string;
}

/**
 * A needs-attention *group* from GET /api/attention — the unit the operator
 * acts on. Identity is `(comicid, base_reason)`, or a singleton release key when
 * the payload carries no comicid (#524). The server owns grouping, labels, and
 * `reason_phrase`; the client never re-derives group identity.
 */
export interface AttentionGroup {
  group_key: string;
  comicid: string | null;
  series_label: string;
  base_reason: string | null;
  reason_phrase: string;
  member_count: number;
  newest_updated_at: string;
  oldest_updated_at: string;
  stage: BandStage | string;
  /**
   * Stage intersection across members — empty for mixed-stage groups, whose
   * rows are resolved by selecting members instead.
   */
  available_actions: BandAction[];
  members: AttentionMember[];
}

/**
 * One subject's story (#428). Identity is `(subject_type, subject_id)`.
 * Opened by an advance, closed by a terminal allowlist pair. Always collapsed.
 */
export interface Story {
  key: string;
  subject_type: string;
  subject_id: string;
  subject_label: string;
  parent_series_id?: string | null;
  /** Opening event's created_at — position, and it never re-sorts. */
  opened_at: string;
  events: TimelineEvent[];
  /** Null while open; the closing event once closed. */
  closer: TimelineEvent | null;
}

export type FeedNode = Story;

export interface TimelinePage {
  results: TimelineEvent[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface BandPage {
  results: AttentionGroup[];
  /** Group count — the same number the status line reports. */
  total: number;
  /** Journal rows behind those groups. */
  member_total: number;
  /** Groups the band shows before folding into the triage route. */
  preview_cap: number;
}
