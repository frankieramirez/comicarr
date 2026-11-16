import { ph, plural, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Gauge, Search } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { approxDuration, untilLabel } from "@/lib/wantedPacing";
import type { WantedPacing } from "@/types";
import { formatNumber } from "@/lib/intl";

function everyLabel(minutes: number): string {
  if (minutes % 1440 === 0) {
    const days = minutes / 1440;
    return plural(days, { one: "every day", other: "every # days" });
  }
  if (minutes % 60 === 0) {
    const hours = minutes / 60;
    return plural(hours, { one: "every hour", other: "every # hours" });
  }
  return plural(minutes, { one: "every minute", other: "every # minutes" });
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

  const every = everyLabel(pacing.search_interval_minutes);
  const days = pacing.new_issue_days;
  const fresh = plural(pacing.indexers, {
    one: `Issues added in the last ${days} days also get a full search on your indexer ${every}.`,
    other: `Issues added in the last ${days} days also get a full search on your # indexers ${every}.`,
  });
  const nextPass = untilLabel(pacing.next_pass_at);

  let title: string;
  let detail: string;
  if (pacing.state === "checking") {
    const perHour = formatNumber(pacing.per_hour);
    const perPass = formatNumber(pacing.per_pass);
    title = t`Auto-search is checking the backlog at ${perHour} an hour`;
    detail = nextPass
      ? t`${perPass} at a time against new releases, newest first. ${fresh} Next batch ${nextPass}.`
      : t`${perPass} at a time against new releases, newest first. ${fresh}`;
  } else if (pacing.state === "waiting_for_feed") {
    title = t`Every Wanted issue has been checked against new releases`;
    detail = t`The next round starts when the feeds bring something new. ${fresh}`;
  } else {
    title = t`Backlog checks are off`;
    detail = t`Only issues added in the last ${ph({ new_issue_days: pacing.new_issue_days })} days are searched automatically. Turn on RSS in Search settings to work through the rest.`;
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
                <Trans>Search settings</Trans>
              </Link>
            </>
          )}
        </p>
      </div>
      {pacing.state === "checking" && pacing.finishes_in_hours != null && (
        <div className="w-48 shrink-0 max-md:w-full">
          <div className="flex items-baseline justify-between gap-3 text-xs">
            <span className="text-foreground-2">
              <Trans>Every issue checked in</Trans>
            </span>
            <span className="font-mono text-foreground">
              {approxDuration(pacing.finishes_in_hours)}
            </span>
          </div>
          <div
            role="progressbar"
            aria-label={t`Backlog checked this round`}
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
          <Trans>Search now…</Trans>
        </Button>
      )}
    </div>
  );
}
