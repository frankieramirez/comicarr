import { Link } from "react-router-dom";
import {
  PanelBody,
  PanelSkeleton,
  SectionHeader,
} from "@/components/dashboard/DashboardPanel";
import {
  sentenceFor,
  subjectHref,
  severityOf,
  type TimelineEvent,
} from "@/components/activity/timeline";
import RelativeTime from "@/components/ui/RelativeTime";
import { useDashboardActivity } from "@/hooks/useDashboard";
import { panelState } from "@/lib/panelState";

/**
 * Recent activity from the narrative stream
 * (docs/architecture/dashboard-spec.md §3.4).
 *
 * The old panel listed `t_snatched` rows, so an attempt that never reached a
 * snatch left no trace — which is how a broken downloader could look like a
 * quiet week. Reading narrative events means failures, blocked routes, and
 * manual reviews share the timeline with successes. Sentences and deep-links
 * match the Activity Center so the two surfaces never invent different prose
 * for the same event.
 */

const ACTIVITY_HREF = "/activity";

function EventHeadline({ event }: { event: TimelineEvent }) {
  const text = sentenceFor(event);
  const href = subjectHref(event);
  const label = event.subject_label;

  if (!href || !label || event.subject_type === "run") {
    return <span>{text}</span>;
  }

  const idx = text.indexOf(label);
  if (idx < 0) {
    return (
      <span>
        {text}{" "}
        <Link to={href} className="hover:underline underline-offset-2">
          {label}
        </Link>
      </span>
    );
  }

  return (
    <span>
      {text.slice(0, idx)}
      <Link to={href} className="hover:underline underline-offset-2">
        {label}
      </Link>
      {text.slice(idx + label.length)}
    </span>
  );
}

function EventRow({ event }: { event: TimelineEvent }) {
  const trouble = severityOf(String(event.status)) === "action_required";

  return (
    <div
      className="flex items-baseline gap-3 py-1 text-[13px]"
      data-testid="recent-activity-row"
      data-status={event.status}
      data-activity={event.activity}
    >
      <div
        className={`min-w-0 flex-1 truncate ${trouble ? "" : "text-foreground"}`}
        style={trouble ? { color: "var(--status-error)" } : undefined}
      >
        <EventHeadline event={event} />
      </div>
      <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
        <RelativeTime value={event.created_at} compact />
      </span>
    </div>
  );
}

/** How many events the rail shows; the full stream lives in Activity. */
const RAIL_ROWS = 6;

export default function RecentActivity() {
  const activity = useDashboardActivity();
  const events = activity.data?.events ?? [];
  const days = activity.data?.days ?? 30;
  const state = panelState(activity, events.length === 0);

  return (
    <section data-testid="recent-activity">
      <SectionHeader
        variant="rail"
        title="Recent activity"
        action={{ label: "Activity", to: ACTIVITY_HREF }}
      />

      <PanelBody
        state={state}
        label="Recent activity"
        skeleton={<PanelSkeleton rows={5} rowHeight={26} />}
        empty={
          <>
            No activity in the last {days} days.{" "}
            <Link
              to={ACTIVITY_HREF}
              className="underline underline-offset-2 hover:text-foreground"
            >
              open full activity
            </Link>
          </>
        }
        onRetry={() => void activity.refetch()}
        isRetrying={activity.isFetching}
      >
        {() => (
          <div>
            {events.slice(0, RAIL_ROWS).map((event) => (
              <EventRow key={String(event.event_id)} event={event} />
            ))}
          </div>
        )}
      </PanelBody>
    </section>
  );
}
