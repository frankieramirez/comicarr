import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatDay, weekLabel } from "@/lib/releaseWeek";
import type { WeekRef, WeeklyPullWeek } from "@/pages/weeklyReleaseRowKey";

/** ‹ This week  Nov 8 – 14 ›, shared by both Releases tabs. */
export default function WeekBar({
  week,
  onNavigate,
}: {
  week: WeeklyPullWeek | undefined;
  onNavigate: (week: WeekRef | null) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      {week && week.offset !== 0 && (
        <Button
          type="button"
          variant="ghost"
          size="compact"
          onClick={() => onNavigate(null)}
        >
          This week
        </Button>
      )}
      <div className="inline-flex h-8 items-stretch overflow-hidden rounded-md border border-border-strong">
        <button
          type="button"
          aria-label="Previous week"
          disabled={!week?.prev}
          onClick={() => week?.prev && onNavigate(week.prev)}
          className="flex w-8 items-center justify-center text-foreground-2 hover:bg-surface-2 disabled:opacity-40"
        >
          <ChevronLeft className="size-3.5" />
        </button>
        <div
          className="flex min-w-0 items-baseline gap-2 self-center border-x border-border-strong px-3 leading-8"
          aria-live="polite"
        >
          <span className="whitespace-nowrap text-[13px] font-medium">
            {week ? weekLabel(week.offset) : "Loading week…"}
          </span>
          {week && (
            <span className="mono-meta truncate max-sm:hidden">
              {formatDay(week.start, false)} – {formatDay(week.end, true)}
            </span>
          )}
        </div>
        <button
          type="button"
          aria-label="Next week"
          disabled={!week?.next}
          onClick={() => week?.next && onNavigate(week.next)}
          className="flex w-8 items-center justify-center text-foreground-2 hover:bg-surface-2 disabled:opacity-40"
        >
          <ChevronRight className="size-3.5" />
        </button>
      </div>
    </div>
  );
}
