import { ph, plural, t } from "@lingui/core/macro";
/**
 * Quiet-count status line for AppStatusBar (Activity Center ADR §9, Variant A).
 * Pure composition — no React, no I/O.
 */

export type ActivityApiState = "online" | "offline" | "checking";

/**
 * Health of the live channel as this status line reads it. `reconnecting`
 * stays silent — only `lost` (a prolonged outage) is worth reporting.
 */
export type LiveConnectionState = "connected" | "reconnecting" | "lost";

export interface ActivityStatusSnapshot {
  /** GET /api/dashboard/library → stats.total_series; null when unavailable */
  librarySeries: number | null;
  /** GET /api/health */
  api: ActivityApiState;
  /**
   * GET /api/activity/status → in_flight
   * (accepted|running run items + OPEN_STAGES journal)
   */
  inFlight: number;
  /** GET /api/activity/status → attention (unresolved band *group* count) */
  attention: number;
  /** SSE health from useServerEvents; only a prolonged loss is reported. */
  live: LiveConnectionState;
}

export type StatusSegmentRole =
  "library" | "api" | "activity" | "attention" | "separator" | "idle";

export interface StatusSegment {
  role: StatusSegmentRole;
  text: string;
  href?: string;
}

export interface QuietStatusMeta {
  line: string;
  segments: StatusSegment[];
}

function libraryText(s: ActivityStatusSnapshot): string {
  if (s.librarySeries === null) return t`library: unavailable`;
  return plural(s.librarySeries, {
    one: "library: # series",
    other: "library: # series",
  });
}

function apiText(s: ActivityStatusSnapshot): string {
  switch (s.api) {
    case "checking":
      return t`api: checking…`;
    case "online":
      return t`api: online`;
    case "offline":
      return t`api: offline`;
    default:
      return t`api: ${ph({ api: s.api })}`;
  }
}

/**
 * Compose the quiet-count status line and segment roles.
 * Attention segment only when K > 0. In-flight links to
 * `/activity?state=in_flight`; idle/unreachable stay on `/activity`.
 */
export function formatQuietStatus(s: ActivityStatusSnapshot): QuietStatusMeta {
  const segments: StatusSegment[] = [];
  segments.push({ role: "library", text: libraryText(s) });
  segments.push({ role: "separator", text: "·" });
  segments.push({ role: "api", text: apiText(s) });
  segments.push({ role: "separator", text: "·" });

  if (s.live === "lost" || (s.api === "offline" && s.librarySeries === null)) {
    segments.push({
      role: "activity",
      text: t`unreachable`,
      href: "/activity",
    });
  } else if (s.inFlight === 0 && s.attention === 0) {
    segments.push({
      role: "idle",
      text: t`idle`,
      href: "/activity",
    });
  } else {
    if (s.inFlight > 0) {
      segments.push({
        role: "activity",
        text: t`${ph({ count: s.inFlight })} in flight`,
        href: "/activity?state=in_flight",
      });
    } else {
      segments.push({
        role: "idle",
        text: t`idle`,
        href: "/activity",
      });
    }
    if (s.attention > 0) {
      segments.push({ role: "separator", text: "·" });
      segments.push({
        role: "attention",
        text: t`⚠ ${ph({ count: s.attention })} need attention`,
        href: "/activity/attention",
      });
    }
  }

  return {
    line: segments.map((seg) => seg.text).join(" "),
    segments,
  };
}

/**
 * aria-live policy: announce offline/recovery, attention appear/change/clear,
 * and idle↔busy only — not mid-flight count ticks.
 */
export function liveAnnouncement(
  prev: ActivityStatusSnapshot | null,
  next: ActivityStatusSnapshot,
): string {
  if (!prev) {
    if (next.live === "lost") return t`Server unreachable`;
    if (next.api === "offline") return t`API offline`;
    if (next.attention > 0)
      return t`${ph({ count: next.attention })} need attention`;
    return "";
  }
  if (prev.live !== next.live) {
    if (next.live === "lost") return t`Server unreachable`;
    if (prev.live === "lost") return t`Reconnected`;
  }
  if (prev.api !== next.api) {
    if (next.api === "offline") return t`API offline`;
    if (next.api === "online" && prev.api === "offline") return t`API online`;
  }
  if (prev.attention !== next.attention) {
    if (next.attention === 0) return t`Attention cleared`;
    return t`${ph({ count: next.attention })} need attention`;
  }
  const prevBusy = prev.inFlight > 0;
  const nextBusy = next.inFlight > 0;
  if (!prevBusy && nextBusy) {
    return t`${ph({ count: next.inFlight })} in flight`;
  }
  if (prevBusy && !nextBusy && next.attention === 0) {
    return t`Idle`;
  }
  return "";
}
