/**
 * The in-flight line's reading of `GET /api/activity/status` — the whole
 * derivation, pure, with no React and no I/O
 * (docs/architecture/dashboard-spec.md §3.3).
 *
 * Two rules shape it:
 *
 * 1. **One definition of the count.** `/api/activity/status` is it. The line
 *    never re-derives "how much work is moving" from a table, which is how the
 *    old Queue tile came to report DDL items only and read "0 queued" while
 *    SABnzbd was downloading.
 * 2. **Recovery qualifies, never adds.** `recovery_pending` is a *subset* of
 *    `in_flight` — work that has already survived a restart. Summing the two
 *    would double-count it, so it only ever appears in parentheses.
 */

export interface InFlightSnapshot {
  /** `in_flight` — total open work across every route. */
  inFlight: number;
  /** `recovery_pending` — the subset that survived a restart. */
  recoveryPending?: number;
}

export interface InFlightView {
  /** The whole line, ready to render. */
  text: string;
  /** Total open work. Zero renders the quiet phrasing rather than a count. */
  count: number;
  /** The qualifier, already bounded by `count`. Zero means no qualifier. */
  recovered: number;
  /** `true` when there is work moving — the loud half of the two states. */
  busy: boolean;
}

/** A count we can stand behind: whole, finite, and never negative. */
function count(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? Math.floor(value)
    : 0;
}

/**
 * Compose the in-flight line.
 *
 * `recoveryPending` is bounded by `inFlight` because the API defines it as a
 * subset of it: a payload claiming more recovered than in flight contradicts
 * itself, and the subset bound is the only reading of it that stays true to
 * the total. It is still never added to the total.
 */
export function inFlightView(snapshot: InFlightSnapshot): InFlightView {
  const total = count(snapshot.inFlight);
  const recovered = Math.min(count(snapshot.recoveryPending), total);

  if (total === 0) {
    return { text: "nothing in flight", count: 0, recovered: 0, busy: false };
  }

  const head = `${total} in flight`;
  const text =
    recovered > 0 ? `${head} (${recovered} recovered from a restart)` : head;

  return { text, count: total, recovered, busy: true };
}
