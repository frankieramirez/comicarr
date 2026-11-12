import { Gauge, Search } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { approxDuration, untilLabel } from "@/lib/wantedPacing";
import type { WantedPacing } from "@/types";

function everyLabel(minutes: number): string {
  if (minutes % 1440 === 0) {
    const days = minutes / 1440;
    return days === 1 ? "every day" : `every ${days} days`;
  }
  if (minutes % 60 === 0) {
    const hours = minutes / 60;
    return hours === 1 ? "every hour" : `every ${hours} hours`;
  }
  return `every ${minutes} minutes`;
}

/**
 * "Auto-search is checking the backlog at 612 an hour" (v2 Wanted design).
 *
 * Older Wanted issues are matched against the indexers' new-release feeds by
 * the RSS watchlist pass, a batch at a time, newest release first; issues
 * added recently also get a full indexer search on the search interval. The
 * numbers come from the pass's own progress, never a guess.
 */
export default function WantedPacingBanner({
  pacing,
  onSearchNow,
  searching,
}: {
  pacing: WantedPacing;
  onSearchNow?: () => void;
  searching?: boolean;
}) {
  if (pacing.state === "idle") return null;

  const fresh = `Issues added in the last ${pacing.new_issue_days} days also get a full search on ${
    pacing.indexers === 1 ? "your indexer" : `your ${pacing.indexers} indexers`
  } ${everyLabel(pacing.search_interval_minutes)}.`;
  const nextPass = untilLabel(pacing.next_pass_at);

  let title: string;
  let detail: string;
  if (pacing.state === "checking") {
    title = `Auto-search is checking the backlog at ${pacing.per_hour.toLocaleString()} an hour`;
    detail = `${pacing.per_pass.toLocaleString()} at a time against new releases, newest first. ${fresh}${
      nextPass ? ` Next batch ${nextPass}.` : ""
    }`;
  } else if (pacing.state === "waiting_for_feed") {
    title = "Every Wanted issue has been checked against new releases";
    detail = `The next round starts when the feeds bring something new. ${fresh}`;
  } else {
    title = "Backlog checks are off";
    detail = `Only issues added in the last ${pacing.new_issue_days} days are searched automatically. Turn on RSS in Search settings to work through the rest.`;
  }

  const share = pacing.total > 0 ? pacing.checked / pacing.total : 0;

  return (
    <div
      data-testid="wanted-pacing"
      className="mx-4 mb-3 flex flex-wrap items-center gap-x-6 gap-y-3 rounded-lg border border-border-subtle bg-surface-1 px-4 py-3 md:mx-8"
    >
      <Gauge
        aria-hidden="true"
        className="size-4 shrink-0 text-muted-foreground max-md:hidden"
      />
      <div className="min-w-0 flex-1 basis-80">
        <p className="text-sm text-foreground">{title}</p>
        <p className="mt-0.5 text-[13px] text-foreground-2 max-md:hidden">
          {detail}
          {pacing.state === "off" && (
            <>
              {" "}
              <Link
                to="/settings?section=search"
                className="text-foreground underline-offset-2 hover:underline"
              >
                Search settings
              </Link>
            </>
          )}
        </p>
      </div>
      {pacing.state === "checking" && pacing.finishes_in_hours != null && (
        <div className="w-48 shrink-0 max-md:w-full">
          <div className="flex items-baseline justify-between gap-3 text-xs">
            <span className="text-foreground-2">Every issue checked in</span>
            <span className="font-mono text-foreground">
              {approxDuration(pacing.finishes_in_hours)}
            </span>
          </div>
          <div
            role="progressbar"
            aria-label="Backlog checked this round"
            aria-valuemin={0}
            aria-valuemax={pacing.total}
            aria-valuenow={pacing.checked}
            className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-3"
          >
            <div
              className="h-full rounded-full"
              style={{
                width: `${Math.max(2, Math.round(share * 100))}%`,
                background: "var(--in-flight)",
              }}
            />
          </div>
        </div>
      )}
      {onSearchNow && (
        <Button
          type="button"
          variant="outline"
          size="toolbar"
          onClick={onSearchNow}
          disabled={searching}
        >
          <Search />
          Search now…
        </Button>
      )}
    </div>
  );
}
