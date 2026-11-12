/**
 * The in-flight line's reading of `GET /api/activity/status` — pure, with no
 * React and no I/O (docs/architecture/dashboard-spec.md §3.3).
 *
 * `recovery_pending` is a *subset* of `in_flight`: work that has already
 * survived a restart. Summing the two would double-count it, so it only ever
 * appears as a qualifier in parentheses.
 */

export interface InFlightSnapshot {
  inFlight: number;
  recoveryPending?: number;
  /** Subset of inFlight not updated for over 7 days. */
  stuck?: number;
}

export interface InFlightView {
  text: string;
  /** There is work moving — the loud half of the two states. */
  busy: boolean;
  /** inFlight minus stuck: the "Moving now" row. */
  moving: number;
  /** The "Stuck over 7 days" row, clamped to inFlight. */
  stuck: number;
  /** Subset that survived a restart, clamped to inFlight. */
  recovered: number;
}

export function inFlightView({
  inFlight,
  recoveryPending = 0,
  stuck = 0,
}: InFlightSnapshot): InFlightView {
  if (inFlight <= 0) {
    return {
      text: "nothing in flight",
      busy: false,
      moving: 0,
      stuck: 0,
      recovered: 0,
    };
  }

  const recovered = Math.min(recoveryPending, inFlight);
  const stuckCount = Math.max(0, Math.min(stuck, inFlight));

  return {
    text:
      recovered > 0
        ? `${inFlight} in flight (${recovered} recovered from a restart)`
        : `${inFlight} in flight`,
    busy: true,
    moving: inFlight - stuckCount,
    stuck: stuckCount,
    recovered,
  };
}
