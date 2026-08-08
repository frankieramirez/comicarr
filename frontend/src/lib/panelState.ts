/**
 * The four states a dashboard panel can be in — and the only place they are
 * derived. Pure composition; no React, no I/O.
 *
 * The point of the enumeration is that "empty" and "unavailable" are separate
 * answers. A panel whose source failed must never fall through to the empty
 * sentence, because a broken pipeline would then read as a quiet one — the
 * failure docs/architecture/dashboard-spec.md exists to prevent.
 */

export type PanelState = "loading" | "unavailable" | "empty" | "content";

export interface PanelQuery {
  isPending: boolean;
  isError: boolean;
}

/**
 * Derive a panel's state from its query. `isEmpty` is consulted only once the
 * query has actually answered — an unanswered panel is never "empty".
 */
export function panelState(query: PanelQuery, isEmpty: boolean): PanelState {
  if (query.isError) return "unavailable";
  if (query.isPending) return "loading";
  return isEmpty ? "empty" : "content";
}
