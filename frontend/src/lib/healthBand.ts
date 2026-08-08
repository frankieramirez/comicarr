/**
 * The health band's reading of `GET /api/search/health` — the whole derivation,
 * pure, with no React and no I/O (docs/architecture/dashboard-spec.md §3.1).
 *
 * Two rules shape everything here:
 *
 * 1. **Absence of evidence is not health.** A missing payload is `unknown`, and
 *    `unknown` renders degraded. Every signal that cannot be substantiated says
 *    so rather than falling through to the healthy phrasing.
 * 2. **Last successful search fails loud on absence.** Every other signal
 *    reports the state of a component; this one reports whether the pipeline has
 *    actually produced a result. It degrades past 2× `SEARCH_INTERVAL` and is
 *    never hidden — in the failure that motivated the spec, every component
 *    reported itself fine while this line read "11 days ago".
 */

import { formatDistanceStrict } from "date-fns";
import type {
  AcquisitionHealthResponse,
  AcquisitionRouteHealth,
  AcquisitionWorkerHealth,
} from "@/hooks/useAcquisitionHealth";
import { sanitizeAcquisitionMessage } from "@/hooks/useAcquisitionHealth";

/** Quiet, amber, red — in escalating order, which is also their precedence. */
export type HealthTone = "healthy" | "degraded" | "blocked";

const TONE_RANK: Record<HealthTone, number> = {
  healthy: 0,
  degraded: 1,
  blocked: 2,
};

/** Where a blocked signal is fixed. Blocked names the component *and* links. */
export interface HealthFix {
  label: string;
  to: string;
}

export interface HealthSignal {
  /** Stable identity for keys and tests, never rendered. */
  key: "route" | "indexers" | "workers" | "gate" | "unknown";
  tone: HealthTone;
  text: string;
  fix?: HealthFix;
}

export interface LastSearchLine {
  /** Epoch seconds of the newest completed provider search, if there is one. */
  at: number | null;
  /** Past 2× `SEARCH_INTERVAL`, or never having run at all. */
  stale: boolean;
  text: string;
}

export interface HealthBandView {
  tone: HealthTone;
  /** `true` when the endpoint itself could not be read. Renders degraded. */
  unknown: boolean;
  signals: HealthSignal[];
  lastSearch: LastSearchLine;
}

const SETTINGS_CLIENTS = "/settings?section=clients";
const SETTINGS_SEARCH = "/settings?section=search";
const SETTINGS_ACQUISITION = "/settings?section=acquisition";

/** Registry default for `SEARCH_INTERVAL`, in minutes. */
export const DEFAULT_SEARCH_INTERVAL_MINUTES = 1440;

/** Downstream keys as `_downstream_readiness` reports them. */
const DOWNSTREAM_LABELS: Record<string, string> = {
  sabnzbd: "SABnzbd",
  nzbget: "NZBGet",
  blackhole: "Blackhole",
  qbittorrent: "qBittorrent",
  transmission: "Transmission",
  deluge: "Deluge",
  rtorrent: "rTorrent",
  utorrent: "uTorrent",
  watchfolder: "Watch folder",
  local: "Direct download",
};

/**
 * Route blockers, nearest-to-ready first, so the phrase names the smallest
 * remaining gap. Mirrors `_ROUTE_REASON_RANK` in `comicarr/app/search/health.py`.
 */
const ROUTE_REASONS: Array<[string, string]> = [
  ["providers_temporarily_blocked", "every indexer is temporarily blocked"],
  ["path_not_ready", "the download directory is not reachable"],
  ["client_not_ready", "the download client is not configured"],
  [
    "unsupported_restart_correlation",
    "the configured client cannot be verified after a restart",
  ],
  ["disabled", "no route is enabled"],
];

const WORKER_LABELS: Record<string, string> = {
  search: "Search",
  downloader: "Download",
  download: "Download",
  postprocess: "Post-processing",
  postprocessing: "Post-processing",
  post_processing: "Post-processing",
};

/** A finite, positive epoch — the client-side twin of `health.py::_timestamp`. */
function timestamp(value: unknown): number | null {
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}

function label(key: string, labels: Record<string, string>): string {
  return labels[key.toLowerCase()] ?? key;
}

/** "a", "a and b", "a, b, and c". */
function listPhrase(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(", ")}, and ${items[items.length - 1]}`;
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function alive(worker: AcquisitionWorkerHealth): boolean {
  return Boolean(worker.alive ?? worker.live ?? worker.healthy);
}

/** The nearest-to-ready blocker across the routes that are not ready. */
function routeBlocker(routes: Array<[string, AcquisitionRouteHealth]>): string {
  const reasons = new Set(
    routes
      .filter(([, route]) => !route.ready)
      .map(([, route]) =>
        String(route.reason ?? "")
          .trim()
          .toLowerCase(),
      ),
  );
  for (const [reason, phrase] of ROUTE_REASONS) {
    if (reasons.has(reason)) return phrase;
  }
  // A maintenance fence puts its own reason in `reason`; the gate signal names
  // it, so the route signal stays silent rather than repeating it verbatim.
  return "";
}

function routeSignal(health: AcquisitionHealthResponse): HealthSignal {
  const routes = Object.entries(health.routes ?? {});
  const ready = routes.filter(([, route]) => route.ready);

  if (health.viable_route && ready.length > 0) {
    const names = Array.from(
      new Set(
        ready.map(([, route]) =>
          label(String(route.downstream ?? ""), DOWNSTREAM_LABELS),
        ),
      ),
    ).filter(Boolean);
    return {
      key: "route",
      tone: "healthy",
      // "ready", not "reachable": the payload reports configured readiness, and
      // claiming reachability it has not probed is the false-confidence §6.1
      // rules out.
      text:
        names.length > 0
          ? `${names.join(" + ")} ready`
          : "Download route ready",
    };
  }

  const blocker = routeBlocker(routes);
  return {
    key: "route",
    tone: "blocked",
    text: blocker
      ? `No usable download route — ${blocker}`
      : "No usable download route",
    fix: { label: "open download clients", to: SETTINGS_CLIENTS },
  };
}

function indexerSignal(health: AcquisitionHealthResponse): HealthSignal {
  const byName = new Map<string, boolean>();
  for (const route of Object.values(health.routes ?? {})) {
    for (const provider of route.providers ?? []) {
      const name = String(provider.name ?? "").trim();
      if (!name) continue;
      // Blocked on any route is blocked: a provider shared by two routes is
      // still one unreachable indexer, not half of one.
      byName.set(
        name,
        (byName.get(name) ?? false) || Boolean(provider.blocked),
      );
    }
  }

  const total = byName.size;
  if (total === 0) {
    return {
      key: "indexers",
      tone: "degraded",
      text: "No indexers configured",
      fix: { label: "open search providers", to: SETTINGS_SEARCH },
    };
  }

  const blocked = Array.from(byName.values()).filter(Boolean).length;
  if (blocked === 0) {
    return {
      key: "indexers",
      tone: "healthy",
      text: `${total} of ${total} indexers responding`,
    };
  }
  return {
    key: "indexers",
    tone: blocked === total ? "blocked" : "degraded",
    text: `${plural(blocked, "indexer")} unreachable`,
    fix: { label: "open search providers", to: SETTINGS_SEARCH },
  };
}

function workerSignal(health: AcquisitionHealthResponse): HealthSignal {
  const workers = Object.entries(health.workers ?? {});

  // No heartbeats at all, or the projection itself failed. Either way the band
  // cannot claim the workers are up.
  if (
    workers.length === 0 ||
    (workers.length === 1 && workers[0][0] === "unavailable")
  ) {
    return {
      key: "workers",
      tone: "degraded",
      text: "Cannot determine worker liveness",
      fix: { label: "open acquisition health", to: SETTINGS_ACQUISITION },
    };
  }

  const down = workers.filter(([, worker]) => !alive(worker));
  if (down.length === 0) {
    const names = workers.map(([name]) => label(name, WORKER_LABELS));
    return {
      key: "workers",
      tone: "healthy",
      text: `${listPhrase(names)} running`,
    };
  }

  const names = down.map(([name]) => label(name, WORKER_LABELS));
  return {
    key: "workers",
    tone: "degraded",
    text: `${listPhrase(names)} worker${down.length === 1 ? "" : "s"} not running`,
    fix: { label: "open acquisition health", to: SETTINGS_ACQUISITION },
  };
}

/**
 * The runtime acquisition gate. Silent when open — a healthy band is one quiet
 * line, and "gate open" is not news.
 */
function gateSignal(health: AcquisitionHealthResponse): HealthSignal | null {
  const maintenance = health.maintenance;
  if (maintenance?.blocked) {
    const reason = maintenance.reason
      ? sanitizeAcquisitionMessage(maintenance.reason)
      : "";
    return {
      key: "gate",
      tone: "degraded",
      text: reason
        ? `Paused for maintenance: ${reason}`
        : "Paused for maintenance",
      fix: { label: "open acquisition health", to: SETTINGS_ACQUISITION },
    };
  }

  const deferred = Number(health.blocked_producer_count ?? 0);
  if (Number.isFinite(deferred) && deferred > 0) {
    return {
      key: "gate",
      tone: "degraded",
      text: `${plural(deferred, "producer")} deferred`,
      fix: { label: "open acquisition health", to: SETTINGS_ACQUISITION },
    };
  }
  return null;
}

/**
 * The newest completed provider search. Never hidden, and loud on absence:
 * "never" is the reading a pipeline that has produced nothing deserves.
 */
function lastSearchLine(
  health: AcquisitionHealthResponse | null,
  searchIntervalMinutes: number,
  now: number,
): LastSearchLine {
  if (!health) {
    return { at: null, stale: true, text: "Last successful search: unknown" };
  }

  const runs = (health.providers ?? [])
    .map((provider) => timestamp(provider.lastrun))
    .filter((value): value is number => value !== null);
  const at = runs.length > 0 ? Math.max(...runs) : null;
  if (at === null) {
    return { at: null, stale: true, text: "Last successful search: never" };
  }

  const interval =
    Number.isFinite(searchIntervalMinutes) && searchIntervalMinutes > 0
      ? searchIntervalMinutes
      : DEFAULT_SEARCH_INTERVAL_MINUTES;
  const ageSeconds = now / 1000 - at;
  const age = formatDistanceStrict(new Date(at * 1000), new Date(now));
  return {
    at,
    stale: ageSeconds > interval * 60 * 2,
    text: `Last successful search: ${age} ago`,
  };
}

function worstTone(tones: HealthTone[]): HealthTone {
  return tones.reduce<HealthTone>(
    (worst, tone) => (TONE_RANK[tone] > TONE_RANK[worst] ? tone : worst),
    "healthy",
  );
}

/**
 * Read the band. `health` is `null` when the endpoint could not be read — which
 * is `unknown`, and renders degraded, never healthy and never absent.
 */
export function healthBandView({
  health,
  searchIntervalMinutes = DEFAULT_SEARCH_INTERVAL_MINUTES,
  now,
}: {
  health: AcquisitionHealthResponse | null;
  searchIntervalMinutes?: number;
  now: number;
}): HealthBandView {
  const lastSearch = lastSearchLine(health, searchIntervalMinutes, now);

  if (!health) {
    return {
      tone: "degraded",
      unknown: true,
      signals: [
        {
          key: "unknown",
          tone: "degraded",
          text: "Cannot determine health",
          fix: { label: "open acquisition health", to: SETTINGS_ACQUISITION },
        },
      ],
      lastSearch,
    };
  }

  const gate = gateSignal(health);
  const signals: HealthSignal[] = [
    routeSignal(health),
    indexerSignal(health),
    workerSignal(health),
    ...(gate ? [gate] : []),
  ];

  return {
    tone: worstTone([
      ...signals.map((signal) => signal.tone),
      // A stale last-successful-search degrades the whole band even when every
      // component reports itself fine. That combination *is* the silent failure.
      lastSearch.stale ? "degraded" : "healthy",
    ]),
    unknown: false,
    signals,
    lastSearch,
  };
}
