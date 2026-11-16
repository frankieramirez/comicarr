import { plural, t } from "@lingui/core/macro";
/**
 * Stage display for needs-attention groups.
 *
 * `failed` and `manual_review` are the same band with a different obligation:
 * one went wrong, the other is waiting on a decision. Colour carries that so
 * the operator can tell them apart without opening triage — the same band, not
 * a second one (#526).
 */

import type { BandAction } from "./types";

export function stageAccent(stage: string): string {
  if (stage === "failed") return "var(--status-error)";
  if (stage === "manual_review") return "var(--status-paused)";
  return "var(--muted-foreground)";
}

export function stageLabel(stage: string): string {
  if (stage === "failed") return t`failed`;
  if (stage === "manual_review") return t`review`;
  return t`mixed`;
}

export function stageDescription(stage: string): string {
  if (stage === "failed") return t`Comicarr couldn't finish this.`;
  if (stage === "manual_review") return t`Waiting on your decision.`;
  return t`Members are at different stages — select the rows you mean.`;
}

const ACTION_LABELS = (): Record<BandAction, string> => ({
  retry: t`Retry`,
  search_again: t`Search again`,
  import: t`Import`,
  stop_wanting: t`Stop wanting`,
});

export function actionLabel(action: BandAction): string {
  return ACTION_LABELS()[action] ?? action;
}

/**
 * Consequence sentence for stop-wanting. Shared by the single-row path and the
 * multi-member confirmation so the two can never describe the same act
 * differently (#525).
 */
export function stopWantingConsequence(count: number, seriesLabel?: string) {
  if (seriesLabel) {
    return plural(count, {
      one: `This issue in ${seriesLabel} will be marked ignored in your library, leave Needs attention, and will not be searched again until you want it back.`,
      other: `These # issues in ${seriesLabel} will be marked ignored in your library, leave Needs attention, and will not be searched again until you want them back.`,
    });
  }
  return plural(count, {
    one: "This issue will be marked ignored in your library, leave Needs attention, and will not be searched again until you want it back.",
    other:
      "These # issues will be marked ignored in your library, leave Needs attention, and will not be searched again until you want them back.",
  });
}
