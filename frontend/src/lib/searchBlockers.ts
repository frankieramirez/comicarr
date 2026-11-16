import { t } from "@lingui/core/macro";
/**
 * Setup gaps that stop *every* search: no indexer, or no download client.
 *
 * Read from `GET /api/search/health` alone, pure, no React. Every screen that
 * would otherwise promise progress ("Searching", "Queued", "Search 117
 * missing") asks this first, so the dashboard, Releases, Wanted and the series
 * page all tell the same story when nothing can run.
 *
 * Only *setup* gaps count. A temporarily blocked indexer or a maintenance pause
 * clears by itself and stays the health band's business; calling those
 * "can't search" would send someone to Settings for nothing.
 */

import type { AcquisitionHealthResponse } from "@/hooks/useAcquisitionHealth";

export const SETTINGS_INDEXERS = "/settings?section=search";
export const SETTINGS_CLIENTS = "/settings?section=clients";

export interface SearchBlocker {
  /** Stable identity for keys and tests, never rendered. */
  key: "indexer" | "client";
  /** The Needs you headline. */
  headline: string;
  /** What it stops, in one line. */
  detail: string;
  /** The short form for row labels: "no indexer". */
  short: string;
  fix: { label: string; to: string };
}

const INDEXER = (): SearchBlocker => ({
  key: "indexer",
  headline: t`No indexer, so nothing can be searched`,
  detail: t`Add Prowlarr, a Newznab or Torznab indexer, or turn on GetComics.`,
  short: t`no indexer`,
  fix: { label: t`Add an indexer`, to: SETTINGS_INDEXERS },
});

const CLIENT = (): SearchBlocker => ({
  key: "client",
  headline: t`No download client, so nothing can be downloaded`,
  detail: t`Add SABnzbd, NZBGet, qBittorrent, or another client.`,
  short: t`no download client`,
  fix: { label: t`Add a download client`, to: SETTINGS_CLIENTS },
});

/** Routes that hand a release to an outside client. DDL downloads itself. */
const CLIENT_ROUTES = ["nzb", "torrent"];

/**
 * The setup gaps, indexer first. Empty when any route is ready, and empty
 * when health is unknown: absence of evidence is not a blocker either, and the
 * health band already says "Cannot determine health".
 */
export function searchBlockers(
  health: AcquisitionHealthResponse | null | undefined,
): SearchBlocker[] {
  if (!health || health.viable_route) return [];
  const routes = health.routes ?? {};
  if (Object.keys(routes).length === 0) return [];

  const configuredIndexers =
    (health.providers?.length ?? 0) +
    Object.values(routes).reduce(
      (sum, route) => sum + Number(route.configured_provider_count ?? 0),
      0,
    );

  const blockers: SearchBlocker[] = [];
  if (configuredIndexers === 0) blockers.push(INDEXER());

  // A DDL provider downloads by itself, so it needs no client. A client that
  // is chosen but half set up (no host, bad path) is a breakage the health
  // band reports in red, not a step never taken.
  const ddlEnabled = Boolean(routes.ddl?.enabled);
  const noClientChosen = CLIENT_ROUTES.every((key) => {
    const route = routes[key];
    return route?.enabled === false || route?.downstream === "disabled";
  });
  if (noClientChosen && !ddlEnabled) blockers.push(CLIENT());
  return blockers;
}

/**
 * Why searching cannot happen, in row-label form ("no indexer"), or null when
 * it can. The indexer gap wins: without one there is nothing to hand a client.
 */
export function searchPausedReason(blockers: SearchBlocker[]): string | null {
  return blockers[0]?.short ?? null;
}
