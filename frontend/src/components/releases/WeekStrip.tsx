import type { UpcomingIssue } from "@/types";
import { releaseDay, releaseState } from "@/lib/releaseState";
import { isoDay, parseDay, weekDays } from "@/lib/releaseWeek";

/**
 * Seven days of the shown week with a count and one dash per release,
 * colored by where that release stands. A glance answers "what lands when".
 */

const MAX_DASHES = 8;
const WEEKDAY = new Intl.DateTimeFormat("en-US", { weekday: "short" });

export default function WeekStrip({
  issues,
  start,
  today = new Date(),
}: {
  issues: UpcomingIssue[];
  /** ISO Sunday that opens the shown week. */
  start: string;
  today?: Date;
}) {
  const todayKey = isoDay(today);

  return (
    <div
      className="grid grid-cols-7 gap-1 rounded-lg border border-border-subtle bg-surface-1 p-1"
      aria-label="Releases by day this week"
      role="group"
    >
      {weekDays(start).map((key) => {
        const date = parseDay(key);
        const landing = issues.filter((issue) => releaseDay(issue) === key);
        const isToday = key === todayKey;
        return (
          <div
            key={key}
            className={`min-w-0 rounded-md px-3 py-2.5 max-sm:px-1.5 ${
              isToday ? "border border-border-strong bg-surface-2" : ""
            }`}
          >
            <div className="flex items-baseline justify-between gap-2 text-[13px]">
              <span
                className={isToday ? "text-foreground" : "text-foreground-2"}
              >
                {WEEKDAY.format(date)}{" "}
                <span className="font-mono text-xs text-muted-foreground">
                  {date.getDate()}
                </span>
              </span>
              {isToday ? (
                <span className="text-[11px] text-foreground-2 max-md:hidden">
                  Today
                </span>
              ) : landing.length > 0 ? (
                <span className="font-mono text-xs text-muted-foreground max-md:hidden">
                  {landing.length}
                </span>
              ) : null}
            </div>
            <div className="mt-2 flex h-1 gap-1" aria-hidden="true">
              {landing.slice(0, MAX_DASHES).map((issue) => (
                <span
                  key={issue.IssueID}
                  className="h-1 w-3 rounded-full"
                  style={{ background: releaseState(issue, todayKey).tone }}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
