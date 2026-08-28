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
}

export interface InFlightView {
  text: string;
  /** There is work moving — the loud half of the two states. */
  busy: boolean;
}

export function inFlightView({
  inFlight,
  recoveryPending = 0,
}: InFlightSnapshot): InFlightView {
  if (inFlight <= 0) {
    return { text: "nothing in flight", busy: false };
  }

  const recovered = Math.min(recoveryPending, inFlight);

  return {
    text:
      recovered > 0
        ? `${inFlight} in flight (${recovered} recovered from a restart)`
        : `${inFlight} in flight`,
    busy: true,
  };
}
