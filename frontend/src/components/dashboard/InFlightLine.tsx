import { ph, plural, t } from "@lingui/core/macro";
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
 *
 * In-flight work splits into "Moving now" and "Stuck over 7 days" (v2
 * dashboard): a two-part bar and one row each, from `in_flight_stuck`.
 */
export default function InFlightLine() {
  const status = useActivityStatus();
  const header = (
    <SectionHeader
      variant="rail"
      title={t`Downloads`}
      action={{ label: t`Activity`, to: "/activity" }}
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
          label={t`In flight`}
          onRetry={() => void status.refetch()}
          isRetrying={status.isFetching}
        />
      </section>
    );
  }

  const view = inFlightView({
    inFlight: status.data?.in_flight ?? 0,
    recoveryPending: status.data?.recovery_pending,
    stuck: status.data?.in_flight_stuck,
  });

  if (!view.busy) {
    return (
      <section>
        {header}
        <Link
          to="/activity"
          aria-label={t`In flight`}
          className="flex items-center gap-2 py-1 text-[13px] text-foreground-2 hover:text-foreground"
        >
          <span
            className="size-1.5 shrink-0 rounded-full"
            style={{ background: "var(--text-muted)" }}
            aria-hidden="true"
          />
          {view.text}
        </Link>
      </section>
    );
  }

  const total = view.moving + view.stuck;
  const rows = [
    { label: t`Moving now`, count: view.moving, color: "var(--status-active)" },
    {
      label: t`Stuck over 7 days`,
      count: view.stuck,
      color: "var(--status-paused)",
    },
  ];

  return (
    <section aria-label={t`In flight`}>
      {header}
      <div
        className="mb-1.5 flex h-[3px] overflow-hidden rounded-full bg-surface-3"
        role="img"
        aria-label={t`${ph({ moving: view.moving })} moving, ${ph({ stuck: view.stuck })} stuck`}
        data-testid="in-flight-bar"
      >
        {rows.map(
          (row) =>
            row.count > 0 && (
              <span
                key={row.label}
                className="h-full"
                style={{
                  width: `${(row.count / total) * 100}%`,
                  minWidth: 3,
                  background: row.color,
                }}
              />
            ),
        )}
      </div>
      <ul>
        {rows.map((row) => (
          <li key={row.label}>
            <Link
              to="/activity"
              className="flex items-center gap-2 py-1 text-[13px] text-foreground-2 hover:text-foreground"
            >
              <span
                className="size-1.5 shrink-0 rounded-full"
                style={{ background: row.color }}
                aria-hidden="true"
              />
              <span className="flex-1">{row.label}</span>
              <span className="font-mono text-xs text-foreground">
                {row.count}
              </span>
            </Link>
          </li>
        ))}
      </ul>
      {view.recovered > 0 && (
        <p className="pl-3.5 text-xs text-muted-foreground">
          {plural(view.recovered, {
            one: "# recovered from a restart",
            other: "# recovered from a restart",
          })}
        </p>
      )}
    </section>
  );
}
