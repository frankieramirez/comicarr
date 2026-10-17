import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ExternalLink, Plus } from "lucide-react";
import { AiSuggestions } from "@/components/weekly/AiSuggestions";
import { Button } from "@/components/ui/button";
import FilterField from "@/components/ui/FilterField";
import { ToggleChip } from "@/components/ui/toggle-chip";
import StatusBadge from "@/components/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import EmptyState from "@/components/ui/EmptyState";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useToast } from "@/components/ui/toast";
import { DESKTOP_COL } from "@/components/data-table/gridColumns";
import { useAiStatus } from "@/hooks/useAiStatus";
import { useQueueIssue } from "@/hooks/useSeries";
import { useAddFromWeek, useWeeklyPullList } from "@/hooks/useWeekly";
import { getErrorMessage } from "@/lib/api";
import { statusTone } from "@/lib/statusTone";
import {
  weeklyReleaseRowKey,
  type WeekRef,
  type WeeklyIssue,
  type WeeklyLibraryState,
  type WeeklyPullWeek,
} from "@/pages/weeklyReleaseRowKey";

const WEEKLY_ROW_COLS =
  "grid-cols-[minmax(0,1fr)_auto_auto] md:grid-cols-[minmax(0,1fr)_80px_160px_110px_120px]";

type SortKey = "title" | "publisher" | "issue";

/**
 * Badge status + label for each library state; also drives the legend. In
 * library borrows the amber Paused token so it never reads as Downloaded green.
 */
const STATE_BADGE: Record<
  WeeklyLibraryState,
  { status: string; label: string }
> = {
  wanted: { status: "Wanted", label: "Wanted" },
  downloaded: { status: "Downloaded", label: "Downloaded" },
  in_library: { status: "Paused", label: "In library" },
  not_in_library: { status: "Not in library", label: "Not in library" },
};

const LEGEND_ORDER: WeeklyLibraryState[] = [
  "wanted",
  "downloaded",
  "in_library",
  "not_in_library",
];

function rowState(issue: WeeklyIssue): WeeklyLibraryState {
  return issue.state ?? "not_in_library";
}

function issueNumber(value: string): number {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : Number.POSITIVE_INFINITY;
}

const byTitle = (a: WeeklyIssue, b: WeeklyIssue) =>
  a.COMIC.localeCompare(b.COMIC, undefined, { sensitivity: "base" }) ||
  issueNumber(a.ISSUE) - issueNumber(b.ISSUE);

const SORTERS: Record<SortKey, (a: WeeklyIssue, b: WeeklyIssue) => number> = {
  title: byTitle,
  publisher: (a, b) =>
    (a.PUBLISHER || "").localeCompare(b.PUBLISHER || "", undefined, {
      sensitivity: "base",
    }) || byTitle(a, b),
  issue: (a, b) => issueNumber(a.ISSUE) - issueNumber(b.ISSUE) || byTitle(a, b),
};

function formatDay(iso: string, withYear: boolean): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: withYear ? "numeric" : undefined,
    timeZone: "UTC",
  });
}

function weekLabel(offset: number): string {
  if (offset === 0) return "This week";
  if (offset === 1) return "Next week";
  if (offset === -1) return "Last week";
  return offset > 1 ? `In ${offset} weeks` : `${-offset} weeks ago`;
}

function comicVineUrl(comicId: string | null): string | null {
  const id = comicId?.replace(/^4050-/, "");
  return id && /^\d+$/.test(id)
    ? `https://comicvine.gamespot.com/volume/4050-${id}/`
    : null;
}

function readWeek(params: URLSearchParams): WeekRef | null {
  const week = params.get("week");
  const year = params.get("year");
  return week && year ? { week, year } : null;
}

export default function IndustryReleasesView() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedWeek = readWeek(searchParams);
  const { data, isLoading, error, refetch } = useWeeklyPullList(selectedWeek);
  const { data: aiStatus } = useAiStatus();
  const [filter, setFilter] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("title");

  const goToWeek = (week: WeekRef | null) => {
    const next = new URLSearchParams(searchParams);
    if (week) {
      next.set("week", week.week);
      next.set("year", week.year);
    } else {
      next.delete("week");
      next.delete("year");
    }
    setSearchParams(next);
  };

  const rows = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const matching = (data?.rows ?? []).filter(
      (row) =>
        !needle ||
        row.COMIC.toLowerCase().includes(needle) ||
        (row.PUBLISHER || "").toLowerCase().includes(needle),
    );
    return [...matching].sort(SORTERS[sortKey]);
  }, [data, filter, sortKey]);

  const counts = useMemo(() => {
    const tally: Record<WeeklyLibraryState, number> = {
      wanted: 0,
      downloaded: 0,
      in_library: 0,
      not_in_library: 0,
    };
    for (const row of data?.rows ?? []) tally[rowState(row)] += 1;
    return tally;
  }, [data]);

  if (error) {
    return (
      <ErrorDisplay
        error={error}
        title="Unable to load weekly pull list"
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <WeekBar week={data} onNavigate={goToWeek} />

      <div className="shrink-0 px-5 py-2.5 border-b border-border flex items-center gap-2 flex-wrap">
        <FilterField
          aria-label="Filter releases"
          placeholder="Filter by title or publisher"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          widthCap="sm"
        />
        <div className="mono-label pl-1">Sort</div>
        {(["title", "publisher", "issue"] as const).map((key) => (
          <ToggleChip
            key={key}
            pressed={sortKey === key}
            onPressedChange={() => setSortKey(key)}
          >
            {key}
          </ToggleChip>
        ))}
        <div
          className="ml-auto flex items-center gap-3 flex-wrap"
          data-testid="weekly-legend"
        >
          {LEGEND_ORDER.map((state) => (
            <StatusBadge
              key={state}
              variant="dot"
              status={STATE_BADGE[state].status}
              label={`${STATE_BADGE[state].label} ${counts[state]}`}
            />
          ))}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-auto">
        {aiStatus?.configured && data?.offset === 0 && (
          <div className="px-5 py-4">
            <AiSuggestions />
          </div>
        )}

        {isLoading ? (
          <div className="px-5 py-4 space-y-2">
            {Array.from({ length: 10 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : !data || data.rows.length === 0 ? (
          <EmptyState
            variant="custom"
            eyebrow="PULL LIST · EMPTY"
            title="No pull list for this week"
            description={
              data?.source === "unavailable"
                ? "Neither Walksoftly nor ComicVine has this week yet. Future weeks fill in as publishers announce them; try again later."
                : "Run a weekly pull list update from Settings to populate this view."
            }
          />
        ) : rows.length === 0 ? (
          <EmptyState
            variant="custom"
            eyebrow="PULL LIST · FILTERED"
            title="Nothing matches that filter"
            description="Clear the filter to see the whole week."
          />
        ) : (
          <WeeklyTable rows={rows} />
        )}
      </div>
    </div>
  );
}

function WeekBar({
  week,
  onNavigate,
}: {
  week: WeeklyPullWeek | undefined;
  onNavigate: (week: WeekRef | null) => void;
}) {
  return (
    <div className="shrink-0 px-5 py-2 border-b border-border flex items-center gap-2">
      <Button
        type="button"
        variant="outline"
        size="icon-sm"
        aria-label="Previous week"
        disabled={!week?.prev}
        onClick={() => week?.prev && onNavigate(week.prev)}
      >
        <ChevronLeft />
      </Button>
      <div className="min-w-0 flex items-baseline gap-2" aria-live="polite">
        <span className="text-[13px] font-semibold">
          {week ? weekLabel(week.offset) : "Loading week…"}
        </span>
        {week && (
          <span className="mono-meta truncate">
            {formatDay(week.start, false)} – {formatDay(week.end, true)}
          </span>
        )}
      </div>
      <Button
        type="button"
        variant="outline"
        size="icon-sm"
        aria-label="Next week"
        disabled={!week?.next}
        onClick={() => week?.next && onNavigate(week.next)}
      >
        <ChevronRight />
      </Button>
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
    </div>
  );
}

function WeeklyTable({ rows }: { rows: WeeklyIssue[] }) {
  const [adding, setAdding] = useState<Set<number>>(() => new Set());
  const addFromWeek = useAddFromWeek();
  const queueIssue = useQueueIssue();
  const queryClient = useQueryClient();
  const { addToast } = useToast();

  const add = async (issue: WeeklyIssue, want: boolean) => {
    if (issue.rowid == null) return;
    const rowid = issue.rowid;
    try {
      const result = await addFromWeek.mutateAsync({ rowid, want });
      setAdding((current) => new Set(current).add(rowid));
      addToast({
        type: "success",
        title: `Adding ${issue.COMIC}`,
        description: result.want_queued
          ? `#${issue.ISSUE} will be marked Wanted once the series is added.`
          : "The series is being added to your library.",
      });
    } catch (err) {
      addToast({ type: "error", message: getErrorMessage(err) });
    }
  };

  const want = async (issue: WeeklyIssue) => {
    if (!issue.library_issue_id) return;
    try {
      await queueIssue.mutateAsync(issue.library_issue_id);
      queryClient.invalidateQueries({ queryKey: ["weekly"] });
      addToast({
        type: "success",
        message: `${issue.COMIC} #${issue.ISSUE} is Wanted.`,
      });
    } catch (err) {
      addToast({ type: "error", message: getErrorMessage(err) });
    }
  };

  return (
    <div data-testid="weekly-releases-table">
      <div
        className={`sticky top-0 z-10 grid ${WEEKLY_ROW_COLS} gap-x-2 md:gap-x-3 mono-label px-5 py-2 border-b bg-background`}
        style={{ borderColor: "var(--border)" }}
      >
        <div>title</div>
        <div className={DESKTOP_COL}>issue</div>
        <div className={DESKTOP_COL}>publisher</div>
        <div>status</div>
        <div className="text-right">
          <span className="sr-only">actions</span>
        </div>
      </div>
      {rows.map((issue, index) => {
        const state = rowState(issue);
        const badge = STATE_BADGE[state];
        const isAdding = issue.rowid != null && adding.has(issue.rowid);
        return (
          <div
            key={weeklyReleaseRowKey(issue, index)}
            data-testid="weekly-release-row"
            className={`grid ${WEEKLY_ROW_COLS} gap-x-2 md:gap-x-3 items-center px-5 py-2 text-[12px] border-b border-border/50`}
          >
            <div className="font-medium truncate" data-grid-title="">
              <ReleaseTitle issue={issue} />
              {issue.ISSUE ? (
                <span
                  data-testid="phone-row-id"
                  className="hidden max-md:inline font-mono text-[11px]"
                  style={{ color: "var(--muted-foreground)" }}
                >
                  {" "}
                  #{issue.ISSUE}
                </span>
              ) : null}
            </div>
            <div className={`${DESKTOP_COL} mono-meta`}>#{issue.ISSUE}</div>
            <div className={`${DESKTOP_COL} text-muted-foreground truncate`}>
              {issue.PUBLISHER}
            </div>
            <div>
              {/* Phones keep only the dot so the title holds half the row. */}
              <span
                role="img"
                aria-label={badge.label}
                title={badge.label}
                className="md:hidden inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: statusTone(badge.status)?.token }}
              />
              <span className={DESKTOP_COL}>
                <StatusBadge
                  variant="dot"
                  status={badge.status}
                  label={badge.label}
                />
              </span>
            </div>
            <div className="flex justify-end">
              {isAdding ? (
                <span className="mono-meta">adding…</span>
              ) : state === "not_in_library" &&
                issue.ComicID &&
                issue.rowid != null ? (
                <DropdownMenu>
                  <DropdownMenuTrigger
                    render={
                      <Button
                        type="button"
                        variant="outline"
                        size="compact"
                        aria-label={`Add ${issue.COMIC}`}
                        disabled={addFromWeek.isPending}
                      />
                    }
                  >
                    <Plus />
                    Add
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" sideOffset={4}>
                    <DropdownMenuItem onClick={() => void add(issue, false)}>
                      Add series
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => void add(issue, true)}>
                      Add series and want #{issue.ISSUE}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              ) : state === "in_library" && issue.library_issue_id ? (
                <Button
                  type="button"
                  variant="outline"
                  size="compact"
                  aria-label={`Want ${issue.COMIC} #${issue.ISSUE}`}
                  disabled={queueIssue.isPending}
                  onClick={() => void want(issue)}
                >
                  Want
                </Button>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ReleaseTitle({ issue }: { issue: WeeklyIssue }) {
  if (issue.in_library && issue.ComicID) {
    return (
      <Link to={`/library/${issue.ComicID}`} className="hover:underline">
        {issue.COMIC}
      </Link>
    );
  }
  const external = comicVineUrl(issue.ComicID);
  if (external) {
    return (
      <a
        href={external}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1 hover:underline"
        title="Open on ComicVine"
      >
        {issue.COMIC}
        <ExternalLink
          className="h-3 w-3 shrink-0"
          style={{ color: "var(--muted-foreground)" }}
          aria-hidden="true"
        />
      </a>
    );
  }
  return <>{issue.COMIC}</>;
}
