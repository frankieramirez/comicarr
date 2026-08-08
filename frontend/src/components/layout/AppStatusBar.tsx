import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useDashboardLibrary } from "@/hooks/useDashboard";
import { useActivityStatus } from "@/hooks/useActivityStatus";
import { useServerEventsHealth } from "@/contexts/ServerEventsContext";
import { apiRequest } from "@/lib/api";
import {
  formatQuietStatus,
  liveAnnouncement,
  type ActivityApiState,
  type ActivityStatusSnapshot,
  type StatusSegment,
} from "@/lib/activityStatus";

const STATUS_POLL_MS = 30 * 1000;

interface HealthResponse {
  status: string;
}

function apiColor(api: ActivityApiState): string | undefined {
  if (api === "online") return "var(--status-active)";
  if (api === "offline") return "var(--status-error)";
  return undefined;
}

/**
 * Compact global status line: library · api · idle|M in flight · optional attention.
 * Activity Center ADR §9 Variant A (quiet counts). Polls status every 30s;
 * shared SSE invalidates the activity status query (no second EventSource).
 */
export default function AppStatusBar() {
  const library = useDashboardLibrary();
  const activity = useActivityStatus();
  const { live } = useServerEventsHealth();
  const health = useQuery<HealthResponse>({
    queryKey: ["app", "health"],
    queryFn: () => apiRequest<HealthResponse>("GET", "/api/health"),
    staleTime: 15 * 1000,
    refetchInterval: STATUS_POLL_MS,
  });

  const libraryPending = library.isPending;
  const libraryFailed = !library.isPending && !library.data;
  const librarySeries = library.data?.stats.total_series ?? 0;

  const api: ActivityApiState = health.isPending
    ? "checking"
    : health.data?.status === "ok"
      ? "online"
      : "offline";

  const activityPending = activity.isPending;
  const activityFailed = !activity.isPending && !activity.data;
  const inFlight = activity.data?.in_flight ?? 0;
  const attention = activity.data?.attention ?? 0;

  const ready = !libraryPending && !health.isPending && !activityPending;

  const snapshot: ActivityStatusSnapshot | null = ready
    ? {
        librarySeries: libraryFailed ? null : librarySeries,
        api,
        inFlight: activityFailed ? 0 : inFlight,
        attention: activityFailed ? 0 : attention,
        live,
      }
    : null;

  const liveText = useStatusLiveRegion(snapshot);

  // Loading shell: same layout, provisional values until queries settle.
  if (!ready) {
    return (
      <StatusShell liveText="">
        <LibrarySegment
          text={
            libraryPending ? "loading…" : libraryFailed ? "unavailable" : null
          }
          seriesCount={libraryFailed || libraryPending ? null : librarySeries}
        />
        <Sep />
        <ApiSegment api={api} />
        <Sep />
        <span className="text-foreground">
          {activityPending ? "loading…" : activityFailed ? "unavailable" : "…"}
        </span>
      </StatusShell>
    );
  }

  // Activity endpoint failed but library/api may still be up — show partial
  // line. A prolonged live-channel loss is the better explanation, so it wins.
  if (
    activityFailed &&
    live !== "lost" &&
    !(libraryFailed && api === "offline")
  ) {
    return (
      <StatusShell liveText={liveText}>
        <LibrarySegment
          text={libraryFailed ? "unavailable" : null}
          seriesCount={libraryFailed ? null : librarySeries}
        />
        <Sep />
        <ApiSegment api={api} />
        <Sep />
        <Link
          to="/activity"
          className="text-foreground hover:underline"
          title="Activity status unavailable — open Activity"
        >
          unavailable
        </Link>
      </StatusShell>
    );
  }

  const meta = formatQuietStatus(snapshot!);

  return (
    <StatusShell liveText={liveText}>
      {meta.segments.map((segment, index) => (
        <SegmentView
          key={`${segment.role}-${index}`}
          segment={segment}
          api={api}
        />
      ))}
    </StatusShell>
  );
}

function StatusShell({
  children,
  liveText,
}: {
  children: ReactNode;
  liveText: string;
}) {
  return (
    <div
      className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-muted-foreground"
      aria-label="Application status"
    >
      {children}
      {/* Outer row is not aria-live; dedicated polite region for policy events only. */}
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {liveText}
      </span>
    </div>
  );
}

function Sep() {
  return <span aria-hidden="true">·</span>;
}

function LibrarySegment({
  text,
  seriesCount,
}: {
  text: string | null;
  seriesCount: number | null;
}) {
  const display =
    text ?? (seriesCount === 1 ? "1 series" : `${seriesCount ?? 0} series`);
  return (
    <span title="Active series in your library">
      library: <span className="text-foreground">{display}</span>
    </span>
  );
}

function ApiSegment({ api }: { api: ActivityApiState }) {
  const display = api === "checking" ? "checking…" : api;
  return (
    <span title="Connection to the Comicarr API">
      api:{" "}
      <span className="text-foreground" style={{ color: apiColor(api) }}>
        {display}
      </span>
    </span>
  );
}

function SegmentView({
  segment,
  api,
}: {
  segment: StatusSegment;
  api: ActivityApiState;
}) {
  if (segment.role === "separator") {
    return <Sep />;
  }

  if (segment.role === "library") {
    // segment.text is "library: N series" — split for styling
    const value = segment.text.replace(/^library:\s*/, "");
    return (
      <span title="Active series in your library">
        library: <span className="text-foreground">{value}</span>
      </span>
    );
  }

  if (segment.role === "api") {
    const value = segment.text.replace(/^api:\s*/, "");
    return (
      <span title="Connection to the Comicarr API">
        api:{" "}
        <span className="text-foreground" style={{ color: apiColor(api) }}>
          {value}
        </span>
      </span>
    );
  }

  if (segment.role === "attention") {
    return (
      <Link
        to={segment.href ?? "/activity/attention"}
        className="font-semibold hover:underline"
        style={{ color: "var(--status-error)" }}
        title="Needs attention → work through them"
      >
        {segment.text}
      </Link>
    );
  }

  // activity | idle
  const title =
    segment.text === "unreachable"
      ? "Server unreachable — open Activity"
      : segment.text === "idle"
        ? "No open work → Activity"
        : "Open work (searches + open pipeline stages) → Activity";

  if (segment.href) {
    return (
      <Link
        to={segment.href}
        className="text-foreground hover:underline"
        title={title}
      >
        {segment.text}
      </Link>
    );
  }

  return <span className="text-foreground">{segment.text}</span>;
}

/**
 * Dedicated polite live region: offline/recovery, attention changes, idle↔busy.
 * Mid-flight count ticks stay silent. Snapshot fields are tracked as primitives
 * so object identity churn does not re-fire announcements.
 */
function useStatusLiveRegion(snapshot: ActivityStatusSnapshot | null): string {
  const [text, setText] = useState("");
  const prevRef = useRef<ActivityStatusSnapshot | null>(null);

  const librarySeries = snapshot?.librarySeries ?? null;
  const api = snapshot?.api;
  const inFlight = snapshot?.inFlight;
  const attention = snapshot?.attention;
  const live = snapshot?.live;
  const ready = snapshot !== null;

  useEffect(() => {
    if (
      !ready ||
      api === undefined ||
      inFlight === undefined ||
      attention === undefined ||
      live === undefined
    ) {
      return;
    }
    const next: ActivityStatusSnapshot = {
      librarySeries,
      api,
      inFlight,
      attention,
      live,
    };
    const announcement = liveAnnouncement(prevRef.current, next);
    prevRef.current = next;
    setText(announcement);
  }, [ready, librarySeries, api, inFlight, attention, live]);

  return text;
}
