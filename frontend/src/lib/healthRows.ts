import type {
  AcquisitionHealthResponse,
  ConnectionCheck,
  ScheduledJobHealth,
} from "@/hooks/useAcquisitionHealth";

/**
 * Activity > Health rows: plain-language background jobs and connections
 * built from /api/system/jobs and /api/search/health. Nothing here fetches.
 */

export type HealthTone = "ok" | "warn" | "fail" | "idle";

export const TONE_COLOR: Record<HealthTone, string> = {
  ok: "var(--status-downloaded)",
  warn: "var(--status-paused)",
  fail: "var(--status-error)",
  idle: "var(--text-muted)",
};

/** Jobs Activity can start early; mirrors RUNNABLE_JOBS on the server. */
export const RUNNABLE_JOBS = new Set([
  "search",
  "rss",
  "monitor",
  "dbupdater",
  "importinbox",
  "manga_sync",
  "weekly",
]);

const JOB_LABELS: Record<string, string> = {
  search: "Search for wanted",
  rss: "RSS check",
  monitor: "Folder monitor",
  importinbox: "Import inbox",
  weekly: "Weekly pull list",
  dbupdater: "Library refresh",
  manga_sync: "Manga library sync",
  version: "Update check",
  ledger_retention: "Ledger cleanup",
  activity_retention: "Activity cleanup",
  interactive_search_retention: "Release search cleanup",
  ddl_health: "Direct download check",
  connection_check: "Connection check",
};

const JOB_ORDER = Object.keys(JOB_LABELS);

const CLIENT_LABELS: Record<string, string> = {
  sabnzbd: "SABnzbd",
  nzbget: "NZBGet",
  qbittorrent: "qBittorrent",
  deluge: "Deluge",
  transmission: "Transmission",
  rtorrent: "rTorrent",
  utorrent: "uTorrent",
  blackhole: "Blackhole folder",
  watchdir: "Watch folder",
};

const ROUTE_LABELS: Record<string, string> = {
  nzb: "Usenet client",
  torrent: "Torrent client",
  ddl: "Direct download",
};

export function toDate(value: number | string | null | undefined): Date | null {
  if (value == null || value === "") return null;
  if (typeof value === "number") return new Date(value * 1000);
  const numeric = Number(value);
  if (Number.isFinite(numeric)) return new Date(numeric * 1000);
  const date = new Date(value.includes("T") ? value : value.replace(" ", "T"));
  return Number.isNaN(date.getTime()) ? null : date;
}

function span(ms: number): string {
  const minutes = Math.round(Math.abs(ms) / 60_000);
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

/** "6h ago", or "just now". */
export function ago(date: Date | null, now = Date.now()): string {
  if (!date) return "—";
  const s = span(now - date.getTime());
  return s === "now" ? "just now" : `${s} ago`;
}

/** "in 18h", or "due now". */
export function until(date: Date | null, now = Date.now()): string {
  if (!date) return "paused";
  if (date.getTime() <= now) return "due now";
  const s = span(date.getTime() - now);
  return s === "now" ? "due now" : `in ${s}`;
}

export interface JobRow {
  id: string;
  label: string;
  tone: HealthTone;
  lastRun: Date | null;
  nextRun: Date | null;
  result: string;
  failing: boolean;
  busy: boolean;
  runnable: boolean;
}

export function jobRows(jobs: ScheduledJobHealth[]): JobRow[] {
  return jobs
    .map((job) => {
      const dispatch = job.dispatch ?? {};
      const lastSuccess = toDate(
        dispatch.last_success ?? job.last_success_timestamp,
      );
      const lastFailure = toDate(
        dispatch.last_failure ?? job.last_failure_timestamp,
      );
      const lastRun =
        toDate(dispatch.last_attempt) ??
        [lastSuccess, lastFailure]
          .filter((d): d is Date => d != null)
          .sort((a, b) => b.getTime() - a.getTime())[0] ??
        null;
      const state = (job.state || job.status || "").toLowerCase();
      const failing =
        state === "error" ||
        (lastFailure != null &&
          (lastSuccess == null || lastFailure > lastSuccess));
      const busy = state === "running" || state === "queued";
      const paused = state === "paused" || !job.next_run_time;
      const error = dispatch.last_error || job.last_error;
      return {
        id: job.id,
        label: JOB_LABELS[job.id] ?? job.name,
        tone: failing
          ? "fail"
          : busy
            ? "warn"
            : paused
              ? "idle"
              : ("ok" as HealthTone),
        lastRun,
        nextRun: toDate(job.next_run_time ?? null),
        result: failing
          ? error || "Failed"
          : state === "running"
            ? "Running now"
            : state === "queued"
              ? "Queued to run"
              : paused
                ? "Paused"
                : lastRun
                  ? job.result || "Finished without errors"
                  : "Hasn't run yet",
        failing,
        busy,
        runnable: RUNNABLE_JOBS.has(job.id) && !paused,
      };
    })
    .sort(
      (a, b) =>
        Number(b.failing) - Number(a.failing) ||
        rank(a.id) - rank(b.id) ||
        a.label.localeCompare(b.label),
    );
}

function rank(id: string): number {
  const index = JOB_ORDER.indexOf(id);
  return index === -1 ? JOB_ORDER.length : index;
}

export interface ConnectionRow {
  key: string;
  label: string;
  tone: HealthTone;
  /** "42 ms", "118 ms median", "local", or "—" before the first check. */
  response: string;
  lastChecked: Date | null;
  result: string;
  settings: string;
  /** Key for POST /api/system/connections/{key}/test; null when untestable. */
  testKey: string | null;
}

function humanize(reason: string | null | undefined): string {
  if (!reason) return "Not ready";
  const text = reason.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function responseLabel(
  check: Pick<ConnectionCheck, "latency_ms" | "latency_label"> | undefined,
): string {
  if (!check) return "—";
  if (check.latency_ms == null)
    return check.latency_label === "local" ? "local" : "—";
  const ms = Math.round(check.latency_ms);
  return check.latency_label === "median" ? `${ms} ms median` : `${ms} ms`;
}

function checkTone(ok: boolean | null | undefined, result: string | null) {
  if (ok === true) return "ok" as HealthTone;
  if (ok === false) return /rate limited/i.test(result ?? "") ? "warn" : "fail";
  return "idle" as HealthTone;
}

const SETTINGS_FOR: Record<string, string> = {
  client: "/settings?section=clients",
  indexers: "/settings?section=search",
  metadata: "/settings?section=api",
};

export function connectionRows(
  health: AcquisitionHealthResponse | undefined,
  checks: ConnectionCheck[] = [],
): ConnectionRow[] {
  const routes = health?.routes ?? {};
  const rows: ConnectionRow[] = [];
  const providers: { name: string; blocked: boolean }[] = [];
  let lastIndexerCheck: Date | null = null;
  const byKey = new Map(checks.map((check) => [check.key, check]));
  const byRoute = new Map(
    checks.filter((check) => check.route).map((check) => [check.route, check]),
  );

  for (const route of ["nzb", "torrent", "ddl"]) {
    const info = routes[route];
    for (const provider of info?.providers ?? []) {
      providers.push(provider);
      const checked = toDate(provider.last_attempt);
      if (checked && (!lastIndexerCheck || checked > lastIndexerCheck))
        lastIndexerCheck = checked;
    }
    const check = byRoute.get(route as ConnectionCheck["route"]);
    if (check && check.checked_at != null) {
      rows.push({
        key: check.key,
        label: check.label,
        tone: checkTone(check.ok, check.result),
        response: responseLabel(check),
        lastChecked: toDate(check.checked_at),
        result: check.result ?? "Not checked yet",
        settings: SETTINGS_FOR.client,
        testKey: check.key,
      });
      continue;
    }
    if (!info || info.configured === false) {
      if (check) {
        rows.push({
          key: check.key,
          label: check.label,
          tone: "idle",
          response: "—",
          lastChecked: null,
          result: "Not checked yet",
          settings: SETTINGS_FOR.client,
          testKey: check.key,
        });
      }
      continue;
    }
    const client = (info.downstream || "").toLowerCase();
    const failing = Boolean(info.last_error) && !info.ready;
    rows.push({
      key: check?.key ?? route,
      label:
        check?.label ?? CLIENT_LABELS[client] ?? ROUTE_LABELS[route] ?? route,
      tone: info.ready ? "ok" : failing ? "fail" : "warn",
      response: "—",
      lastChecked: toDate(info.last_attempt ?? null),
      result: info.ready
        ? info.blocked_provider_count
          ? `Ready, ${info.blocked_provider_count} indexer${info.blocked_provider_count === 1 ? "" : "s"} paused`
          : "Ready"
        : info.last_error || humanize(info.reason),
      settings: SETTINGS_FOR.client,
      testKey: check?.key ?? null,
    });
  }

  const indexers = byKey.get("indexers");
  if (indexers && indexers.checked_at != null) {
    const total = indexers.count ?? providers.length;
    const responding = indexers.responding ?? (indexers.ok ? total : 0);
    rows.push({
      key: "indexers",
      label: `Indexers, ${responding} of ${total}`,
      tone: indexers.ok ? "ok" : responding > 0 ? "warn" : "fail",
      response: responseLabel(indexers),
      lastChecked: toDate(indexers.checked_at),
      result: indexers.result ?? "",
      settings: SETTINGS_FOR.indexers,
      testKey: "indexers",
    });
  } else if (providers.length > 0) {
    const blocked = providers.filter((p) => p.blocked).length;
    const live = providers.length - blocked;
    rows.push({
      key: "indexers",
      label: `Indexers, ${live} of ${providers.length}`,
      tone: blocked === 0 ? "ok" : live === 0 ? "fail" : "warn",
      response: "—",
      lastChecked: lastIndexerCheck,
      result:
        blocked === 0 ? "All responding" : `${blocked} paused after errors`,
      settings: SETTINGS_FOR.indexers,
      testKey: indexers ? "indexers" : null,
    });
  }

  for (const check of checks) {
    if (check.kind !== "metadata") continue;
    rows.push({
      key: check.key,
      label: check.label,
      tone: checkTone(check.ok, check.result),
      response: responseLabel(check),
      lastChecked: toDate(check.checked_at),
      result: check.result ?? "Not checked yet",
      settings: SETTINGS_FOR.metadata,
      testKey: check.key,
    });
  }
  return rows;
}
