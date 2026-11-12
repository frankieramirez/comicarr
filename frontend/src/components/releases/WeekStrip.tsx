import type { UpcomingIssue } from "@/types";

/**
 * Seven days of the current week with a count and one dash per release,
 * colored by where that release stands. A glance answers "what lands when".
 */

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MAX_DASHES = 8;

function isoDay(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function weekDays(today: Date): Date[] {
  const monday = new Date(today);
  monday.setHours(0, 0, 0, 0);
  monday.setDate(today.getDate() - ((today.getDay() + 6) % 7));
  return Array.from({ length: 7 }, (_, i) => {
    const day = new Date(monday);
    day.setDate(monday.getDate() + i);
    return day;
  });
}

function releaseDay(issue: UpcomingIssue): string {
  return String(issue.IssueDate || issue.ReleaseDate || "").slice(0, 10);
}

function dashColor(status?: string | null): string {
  const value = (status || "").toLowerCase();
  if (value === "downloaded" || value === "archived")
    return "var(--status-downloaded)";
  if (value === "snatched") return "var(--in-flight)";
  if (value === "wanted") return "var(--status-wanted)";
  return "var(--text-muted)";
}

export default function WeekStrip({
  issues,
  today = new Date(),
}: {
  issues: UpcomingIssue[];
  today?: Date;
}) {
  const days = weekDays(today);
  const todayKey = isoDay(today);

  return (
    <div
      className="grid grid-cols-7 gap-1 rounded-lg border border-border-subtle bg-surface-1 p-1"
      aria-label="Releases by day this week"
      role="group"
    >
      {days.map((day, index) => {
        const key = isoDay(day);
        const landing = issues.filter((issue) => releaseDay(issue) === key);
        const isToday = key === todayKey;
        return (
          <div
            key={key}
            className={`min-w-0 rounded-md px-3 py-2.5 ${
              isToday ? "border border-border-strong bg-surface-2" : ""
            }`}
          >
            <div className="flex items-baseline justify-between gap-2 text-[13px]">
              <span
                className={isToday ? "text-foreground" : "text-foreground-2"}
              >
                {DAY_NAMES[index]}{" "}
                <span className="font-mono text-xs text-muted-foreground">
                  {day.getDate()}
                </span>
              </span>
              {isToday ? (
                <span className="text-[11px] text-foreground-2">Today</span>
              ) : landing.length > 0 ? (
                <span className="font-mono text-xs text-muted-foreground">
                  {landing.length}
                </span>
              ) : null}
            </div>
            <div className="mt-2 flex h-1 gap-1" aria-hidden="true">
              {landing.slice(0, MAX_DASHES).map((issue) => (
                <span
                  key={issue.IssueID}
                  className="h-1 w-3 rounded-full"
                  style={{ background: dashColor(issue.Status) }}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
