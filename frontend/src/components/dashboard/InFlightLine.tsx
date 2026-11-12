import { Link } from "react-router-dom";
import { useActivityStatus } from "@/hooks/useActivityStatus";
import { inFlightView } from "@/lib/inFlight";
import {
  PanelUnavailable,
  SectionHeader,
} from "@/components/dashboard/DashboardPanel";
import { Skeleton } from "@/components/ui/skeleton";

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
  const header = (
    <SectionHeader
      variant="rail"
      title="Downloads"
      action={{ label: "Activity", to: "/activity" }}
    />
  );

  if (status.isPending) {
    return (
      <section>
        {header}
        <Skeleton aria-hidden="true" className="my-1.5 h-2.5 w-40 rounded-sm" />
      </section>
    );
  }

  if (status.isError) {
    return (
      <section>
        {header}
        <PanelUnavailable
          label="In flight"
          onRetry={() => void status.refetch()}
          isRetrying={status.isFetching}
        />
      </section>
    );
  }

  const view = inFlightView({
    inFlight: status.data?.in_flight ?? 0,
    recoveryPending: status.data?.recovery_pending,
  });

  return (
    <section>
      {header}
      <Link
        to="/activity"
        aria-label="In flight"
        className="flex items-center gap-2 py-1 text-[13px] hover:text-foreground"
      >
        <span
          className="size-1.5 shrink-0 rounded-full"
          style={{
            background: view.busy ? "var(--in-flight)" : "var(--text-muted)",
          }}
          aria-hidden="true"
        />
        <span className={view.busy ? "text-foreground" : "text-foreground-2"}>
          {view.text}
        </span>
      </Link>
    </section>
  );
}
