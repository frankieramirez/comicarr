import { ph, plural, t } from "@lingui/core/macro";
import type { WantedSeries } from "@/types";
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

function tries(attemptCount: number): number {
  return Number.isFinite(attemptCount)
    ? Math.max(0, Math.trunc(attemptCount))
    : 0;
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
    return t`never searched`;
  }

  const state = String(acquisition.state).toLowerCase();
  const attempts = Number(acquisition.attempt_count) || 0;

  if (state === "accepted" || state === "running") {
    return t`searching…`;
  }
  if (state === "no_match") {
    return plural(tries(attempts), {
      one: "no match · # try",
      other: "no match · # tries",
    });
  }
  if (state === "failed" || state === "quarantined") {
    return plural(tries(attempts), {
      one: "failed · # try",
      other: "failed · # tries",
    });
  }
  if (state === "blocked") {
    return t`blocked`;
  }
  if (state === "cancelled") {
    return t`cancelled`;
  }
  if (state === "succeeded") {
    return t`matched`;
  }

  return state.replace(/_/g, " ");
}

/** "Not found 3×", "Searching", "Queued". */
export function wantedSeriesWhy(
  series: Pick<WantedSeries, "why" | "max_attempts">,
): string {
  if (series.why === "not_found") {
    return series.max_attempts > 1
      ? t`Not found ${ph({ max_attempts: series.max_attempts })}×`
      : t`Not found`;
  }
  return series.why === "searching" ? t`Searching` : t`Queued`;
}
