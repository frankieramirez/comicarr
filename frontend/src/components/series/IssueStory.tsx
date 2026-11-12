import { Link } from "react-router-dom";
import { CheckCircle2, Circle, XCircle } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import {
  actionLabel,
  reasonDetailLine,
  sentenceFor,
  severityOf,
  type AttentionCause,
  type BandAction,
  type TimelineEvent,
} from "@/components/activity/timeline";
import {
  useActivityTimeline,
  useBandBatchResolution,
} from "@/hooks/useActivity";
import { getErrorMessage } from "@/lib/api";

/** Actions the issue page can take in one click; the rest need a dialog. */
const ONE_CLICK: BandAction[] = ["retry", "search_again"];

const WHEN = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function when(iso: string): string {
  const date = new Date(iso.includes("T") ? iso : iso.replace(" ", "T"));
  return Number.isNaN(date.getTime()) ? iso : WHEN.format(date);
}

function StepIcon({ event }: { event: TimelineEvent }) {
  if (
    severityOf(event.status) === "action_required" ||
    event.status === "failed"
  )
    return (
      <XCircle
        aria-label="Failed"
        className="size-4 shrink-0"
        style={{ color: "var(--status-error)" }}
      />
    );
  if (event.status === "succeeded")
    return (
      <CheckCircle2
        aria-label="Done"
        className="size-4 shrink-0"
        style={{ color: "var(--status-downloaded)" }}
      />
    );
  return (
    <Circle
      aria-label={event.status}
      className="size-4 shrink-0 text-muted-foreground"
    />
  );
}

export function IssueCauseActions({ cause }: { cause: AttentionCause }) {
  const resolve = useBandBatchResolution();
  const { addToast } = useToast();
  const actions = ONE_CLICK.filter((action) =>
    cause.available_actions.includes(action),
  );
  return (
    <>
      {actions.map((action, index) => (
        <Button
          key={action}
          type="button"
          size="toolbar"
          variant={index === 0 ? "default" : "outline"}
          disabled={resolve.isPending}
          onClick={async () => {
            try {
              await resolve.mutateAsync({
                releaseKeys: cause.release_keys,
                action,
              });
              addToast({
                type: "success",
                message:
                  action === "retry"
                    ? "Retrying this issue."
                    : "Searching for this issue again.",
              });
            } catch (err) {
              addToast({ type: "error", message: getErrorMessage(err) });
            }
          }}
        >
          {actionLabel(action)}
        </Button>
      ))}
    </>
  );
}

/**
 * "What happened" for one issue (v2 design 07): its activity, oldest
 * first, each step with a plain sentence, then the likely cause when the
 * issue is in Needs you.
 */
export default function IssueStory({
  issueId,
  cause,
}: {
  issueId: string;
  cause: AttentionCause | null;
}) {
  const timeline = useActivityTimeline({
    scope_type: "issue",
    scope_id: issueId,
  });
  const events = (timeline.data?.pages ?? [])
    .flatMap((page) => page.results)
    .slice()
    .reverse();

  return (
    <section aria-labelledby="issue-story" className="min-w-0">
      <h2
        id="issue-story"
        className="pb-4 text-[15px] font-semibold text-foreground"
      >
        What happened
      </h2>
      {timeline.isPending ? (
        <div className="space-y-3">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      ) : events.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">
          Nothing has happened to this issue yet. Searches, downloads and
          imports show up here as they run.
        </p>
      ) : (
        <ol className="space-y-5">
          {events.map((event) => {
            const line = reasonDetailLine(
              event.reason_code,
              event.reason_detail,
            );
            // The timeline lexicon is short; the server's attention copy
            // names this issue's own failure better than "something went
            // wrong".
            const detail =
              line.rawCode && cause?.base_reason === line.rawCode
                ? { ...line, phrase: cause.reason_phrase }
                : line;
            return (
              <li
                key={event.event_id}
                data-testid="issue-story-step"
                className="grid grid-cols-[16px_minmax(0,1fr)_auto] gap-x-3 gap-y-1"
              >
                <span className="pt-0.5">
                  <StepIcon event={event} />
                </span>
                <span className="text-sm text-foreground">
                  {sentenceFor(event)}
                </span>
                <time
                  dateTime={event.created_at}
                  className="font-mono text-xs whitespace-nowrap text-muted-foreground"
                >
                  {when(event.created_at)}
                </time>
                {(detail.phrase || detail.detail) && (
                  <span className="col-start-2 col-span-2 text-[13px] text-foreground-2">
                    {detail.phrase && (
                      <span className="block">
                        {detail.phrase.charAt(0).toUpperCase() +
                          detail.phrase.slice(1)}
                        .
                      </span>
                    )}
                    {detail.detail && (
                      <span className="block break-all font-mono text-xs text-muted-foreground">
                        {detail.detail}
                      </span>
                    )}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      )}

      {cause && (
        <div
          data-testid="issue-likely-cause"
          className="mt-5 rounded-lg border border-border-strong bg-surface-1 p-4 sm:ml-7"
        >
          <div className="flex items-center gap-2 text-sm font-medium text-foreground">
            <span
              aria-hidden="true"
              className="size-1.5 rounded-full"
              style={{ background: "var(--status-error)" }}
            />
            Likely cause: {cause.headline}
          </div>
          {cause.hint && (
            <p className="mt-1.5 text-[13px] text-foreground-2">{cause.hint}</p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {cause.fix && (
              <Link
                to={cause.fix.href}
                className={buttonVariants({
                  variant: "outline",
                  size: "toolbar",
                })}
              >
                {cause.fix.label}
              </Link>
            )}
            <Link
              to="/activity/attention"
              className={buttonVariants({ variant: "ghost", size: "toolbar" })}
            >
              More options in Needs you
            </Link>
          </div>
        </div>
      )}
    </section>
  );
}
