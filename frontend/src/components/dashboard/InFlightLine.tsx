import { Link } from "react-router-dom";
import { useActivityStatus } from "@/hooks/useActivityStatus";
import { inFlightView } from "@/lib/inFlight";
import { PanelUnavailable } from "@/components/dashboard/DashboardPanel";

/**
 * How much work is moving right now, across every route
 * (docs/architecture/dashboard-spec.md §3.3).
 *
 * It reads `GET /api/activity/status` and nothing else — the same source the
 * global status indicator reads, so the two can never disagree. That is the
 * point of replacing the Queue tile, which counted active DDL items only and
 * so read "0 queued" while SABnzbd was actively downloading (§3.7). A failed
 * read says so rather than falling through to "nothing in flight".
 */
export default function InFlightLine() {
  const status = useActivityStatus();

  if (status.isPending) {
    return (
      <div className="px-5 py-2.5 border-b border-border">
        <div
          aria-hidden="true"
          className="h-2.5 w-40 animate-pulse rounded-[2px] bg-primary/10"
        />
      </div>
    );
  }

  if (status.isError) {
    return (
      <div className="px-5 border-b border-border">
        <PanelUnavailable
          label="In flight"
          onRetry={() => void status.refetch()}
          isRetrying={status.isFetching}
        />
      </div>
    );
  }

  const view = inFlightView({
    inFlight: status.data?.in_flight ?? 0,
    recoveryPending: status.data?.recovery_pending,
  });

  return (
    <div className="px-5 py-2.5 border-b border-border">
      <Link
        to="/activity"
        aria-label="In flight"
        className="font-mono text-[11px] hover:text-foreground"
        style={{
          color: view.busy ? "var(--status-active)" : "var(--muted-foreground)",
        }}
      >
        {view.text}
      </Link>
    </div>
  );
}
