/**
 * Query-key vocabulary for the Activity Center surfaces.
 *
 * A leaf on purpose — no imports at all. The hooks that read these keys and
 * the SSE listener that stales them must agree on one spelling, but a hook
 * asking for a cache key should not drag the timeline's prose templates in
 * behind it.
 */

export const ACTIVITY_TIMELINE_QUERY_KEY = ["activity", "timeline"] as const;
export const ACTIVITY_BAND_QUERY_KEY = ["activity", "band"] as const;
export const ACTIVITY_STATUS_QUERY_KEY = ["activity", "status"] as const;
export const ACTIVITY_IN_FLIGHT_QUERY_KEY = ["activity", "in-flight"] as const;

/**
 * Every key a narrated event stales: the narrative feed plus the derived
 * projections beside it. Invalidated as one batch, never piecemeal — a run
 * that grabs 40 issues must cost one refetch round, not 40.
 */
export const ACTIVITY_INVALIDATION_KEYS: readonly (readonly string[])[] = [
  ACTIVITY_TIMELINE_QUERY_KEY,
  ACTIVITY_BAND_QUERY_KEY,
  ACTIVITY_STATUS_QUERY_KEY,
  ACTIVITY_IN_FLIGHT_QUERY_KEY,
];
