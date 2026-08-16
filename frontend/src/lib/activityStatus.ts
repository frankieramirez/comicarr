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

function seriesLabel(n: number): string {
  return n === 1 ? "1 series" : `${n} series`;
}

function libraryText(s: ActivityStatusSnapshot): string {
  if (s.librarySeries === null) return "library: unavailable";
  return `library: ${seriesLabel(s.librarySeries)}`;
}

function apiText(s: ActivityStatusSnapshot): string {
  return `api: ${s.api === "checking" ? "checking…" : s.api}`;
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

  // Counts sourced from a server we cannot reach are stale, whichever channel
  // proved it — a prolonged SSE loss says so sooner than the 30s health poll.
  if (s.live === "lost" || (s.api === "offline" && s.librarySeries === null)) {
    segments.push({
      role: "activity",
      text: "unreachable",
      href: "/activity",
    });
  } else if (s.inFlight === 0 && s.attention === 0) {
    segments.push({
      role: "idle",
      text: "idle",
      href: "/activity",
    });
  } else {
    if (s.inFlight > 0) {
      segments.push({
        role: "activity",
        text: `${s.inFlight} in flight`,
        href: "/activity?state=in_flight",
      });
    } else {
      segments.push({
        role: "idle",
        text: "idle",
        href: "/activity",
      });
    }
    if (s.attention > 0) {
      segments.push({ role: "separator", text: "·" });
      segments.push({
        role: "attention",
        // The count is *groups* — distinct problems, not journal rows — and it
        // lands on the triage route rather than the timeline, because the only
        // reason to click it is to work through them.
        text: `⚠ ${s.attention} need attention`,
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
    if (next.live === "lost") return "Server unreachable";
    if (next.api === "offline") return "API offline";
    if (next.attention > 0) return `${next.attention} need attention`;
    return "";
  }
  // Reachability outranks every count: stale numbers are not worth announcing.
  if (prev.live !== next.live) {
    if (next.live === "lost") return "Server unreachable";
    if (prev.live === "lost") return "Reconnected";
  }
  if (prev.api !== next.api) {
    if (next.api === "offline") return "API offline";
    if (next.api === "online" && prev.api === "offline") return "API online";
  }
  if (prev.attention !== next.attention) {
    if (next.attention === 0) return "Attention cleared";
    return `${next.attention} need attention`;
  }
  const prevBusy = prev.inFlight > 0;
  const nextBusy = next.inFlight > 0;
  if (!prevBusy && nextBusy) {
    return `${next.inFlight} in flight`;
  }
  if (prevBusy && !nextBusy && next.attention === 0) {
    return "Idle";
  }
  return "";
}
