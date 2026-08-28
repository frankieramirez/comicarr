/**
 * Operator-language labels for Wanted row live-sticky acquisition annotations.
 *
 * Source of truth for *which* item annotates a row is the latest search
 * `acquisition_run_items` row (backend). This module only maps that derived
 * state into the approved Wanted vocabulary — no progress %, no fabricated
 * `next_attempt_at` countdowns (#429 / #432 / #490).
 */

export type WantedAcquisitionState =
  | "accepted"
  | "running"
  | "succeeded"
  | "no_match"
  | "blocked"
  | "failed"
  | "quarantined"
  | "cancelled"
  | string;

export interface WantedAcquisitionAnnotation {
  state: WantedAcquisitionState | null;
  attempt_count: number;
  reason?: string | null;
  run_id?: string | null;
  entity_type?: string | null;
  updated_at?: string | null;
  completed_at?: string | null;
}

/** Approved operator phrases for the common Wanted sticky states. */
export const WANTED_ANNOTATION_NEVER_SEARCHED = "never searched";
export const WANTED_ANNOTATION_SEARCHING = "searching…";

function triesClause(attemptCount: number): string {
  const n = Number.isFinite(attemptCount)
    ? Math.max(0, Math.trunc(attemptCount))
    : 0;
  return `${n} ${n === 1 ? "try" : "tries"}`;
}

/**
 * Render the sticky Status cell for one Wanted row.
 *
 * - no annotation / null state → `never searched`
 * - accepted | running → `searching…`
 * - no_match → `no match · N tries`
 * - other terminal ledger states stay honest and countdown-free
 */
export function formatWantedAcquisitionAnnotation(
  acquisition: WantedAcquisitionAnnotation | null | undefined,
): string {
  if (!acquisition || acquisition.state == null || acquisition.state === "") {
    return WANTED_ANNOTATION_NEVER_SEARCHED;
  }

  const state = String(acquisition.state).toLowerCase();
  const attempts = Number(acquisition.attempt_count) || 0;

  if (state === "accepted" || state === "running") {
    return WANTED_ANNOTATION_SEARCHING;
  }
  if (state === "no_match") {
    return `no match · ${triesClause(attempts)}`;
  }
  if (state === "failed" || state === "quarantined") {
    return `failed · ${triesClause(attempts)}`;
  }
  if (state === "blocked") {
    return "blocked";
  }
  if (state === "cancelled") {
    return "cancelled";
  }
  if (state === "succeeded") {
    return "matched";
  }

  return state.replace(/_/g, " ");
}
