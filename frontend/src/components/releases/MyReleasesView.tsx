import { useEffect, useMemo, useState, type ReactNode } from "react";
import { RefreshCw, Search } from "lucide-react";
import {
  useForceSearch,
  useBulkQueueIssues,
  useBulkUnqueueIssues,
  describeBulkResult,
  type BulkIssueResult,
} from "@/hooks/useQueue";
import { useRetrySearchRun } from "@/hooks/useSeries";
import { Button } from "@/components/ui/button";
import FilterField from "@/components/ui/FilterField";
import WeekStrip from "@/components/releases/WeekStrip";
import type { ReleaseFormat } from "@/components/releases/releaseFormat";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { DataTable } from "@/components/data-table/DataTable";
import { useUpcomingColumns } from "@/components/queue/upcomingColumns";
import BulkActionBar from "@/components/queue/BulkActionBar";
import { useTableState } from "@/components/data-table/useTableState";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import EmptyState from "@/components/ui/EmptyState";
import { ReleaseReviewSheet } from "@/components/releases/ReleaseReviewSheet";
import { useInteractiveReview } from "@/hooks/useInteractiveSearch";
import {
  isNewComicDay,
  releaseDay,
  releaseState,
  type ReleaseBucket,
} from "@/lib/releaseState";
import { dayHeading, isoDay, weekStart } from "@/lib/releaseWeek";
import { useIsMobile } from "@/hooks/use-mobile";
import { useActivityBand } from "@/hooks/useActivity";
import { useSearchBlockers } from "@/hooks/useAcquisitionHealth";
import SearchBlockedBanner from "@/components/releases/SearchBlockedBanner";
import type { UpcomingIssue } from "@/types";

type StateTab = "all" | Exclude<ReleaseBucket, "other">;

const TABS: { value: StateTab; label: string }[] = [
  { value: "all", label: "All" },
  { value: "needs_you", label: "Needs you" },
  { value: "in_progress", label: "In progress" },
  { value: "downloaded", label: "Downloaded" },
  { value: "coming_up", label: "Coming up" },
];

const byDayThenName = (a: UpcomingIssue, b: UpcomingIssue) =>
  releaseDay(a).localeCompare(releaseDay(b)) ||
  (a.ComicName || "").localeCompare(b.ComicName || "", undefined, {
    sensitivity: "base",
  });

/**
 * Releases > Mine (v8 design): the shown week's issues and chapters from
 * followed series, grouped under a heading per release day, with tabs that
 * say where each one stands.
 */
export default function MyReleasesView({
  modeBar,
  format,
  issues,
  isLoading,
  isFetching,
  error,
  refetch,
  start,
}: {
  /** The shared format chips and "Only my library" toggle. */
  modeBar: (counts?: Partial<Record<ReleaseFormat, number>>) => ReactNode;
  /** All, comics, or manga (the library cannot tell manhwa apart). */
  format: ReleaseFormat;
  issues: UpcomingIssue[];
  isLoading: boolean;
  isFetching: boolean;
  error: unknown;
  refetch: () => unknown;
  /** ISO Sunday that opens the shown week; the current week until known. */
  start?: string;
}) {
  const today = isoDay(new Date());
  const [tab, setTab] = useState<StateTab>("all");
  const [filter, setFilter] = useState("");
  const forceSearchMutation = useForceSearch();
  const retrySearchMutation = useRetrySearchRun();
  const [forceRunId, setForceRunId] = useState<string | null>(null);
  const bulkQueueMutation = useBulkQueueIssues();
  const bulkUnqueueMutation = useBulkUnqueueIssues();
  const { addToast } = useToast();
  const { startReview, reviewSheetProps } = useInteractiveReview();
  const { blockers, pausedReason } = useSearchBlockers();

  const startIssueReview = (issue: UpcomingIssue) =>
    startReview(issue, {
      entityType: issue.annual ? "annual" : "issue",
      entityId: issue.IssueID,
    });

  const kindAndText = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return issues.filter(
      (issue) =>
        (format === "all" ||
          (format === "manga") === (issue.ContentType === "manga")) &&
        (!needle ||
          (issue.ComicName || "").toLowerCase().includes(needle) ||
          (issue.Publisher || "").toLowerCase().includes(needle)),
    );
  }, [issues, format, filter]);

  const counts = useMemo(() => {
    const tally: Record<StateTab, number> = {
      all: kindAndText.length,
      needs_you: 0,
      in_progress: 0,
      downloaded: 0,
      coming_up: 0,
    };
    for (const issue of kindAndText) {
      const bucket = releaseState(issue, today, undefined, pausedReason).bucket;
      if (bucket !== "other") tally[bucket] += 1;
    }
    return tally;
  }, [kindAndText, today, pausedReason]);

  const rows = useMemo(
    () =>
      kindAndText
        .filter(
          (issue) =>
            tab === "all" ||
            releaseState(issue, today, undefined, pausedReason).bucket === tab,
        )
        .sort(byDayThenName),
    [kindAndText, tab, today, pausedReason],
  );

  const dayCounts = useMemo(() => {
    const tally = new Map<string, number>();
    for (const issue of rows) {
      const day = releaseDay(issue);
      tally.set(day, (tally.get(day) ?? 0) + 1);
    }
    return tally;
  }, [rows]);

  // Needs you causes carry the one place that clears them ("Fix command").
  const band = useActivityBand();
  const fixes = useMemo(() => {
    const map = new Map<string, { label: string; href: string }>();
    for (const cause of band.data?.causes ?? []) {
      if (cause.base_reason && cause.fix && !map.has(cause.base_reason))
        map.set(cause.base_reason, cause.fix);
    }
    return map;
  }, [band.data]);
  const columns = useUpcomingColumns(
    (issue) => void startIssueReview(issue),
    today,
    fixes,
    pausedReason,
  );
  const { table, selectedIds, clearSelection } = useTableState({
    data: rows,
    columns,
    getRowId: (row) => row.IssueID,
    selection: { scope: "filtered" },
  });

  // Phones keep cover, series, number, and status; the rest is desktop-only.
  const isMobile = useIsMobile();
  useEffect(() => {
    table.setColumnVisibility(
      isMobile ? { select: false, Publisher: false, actions: false } : {},
    );
  }, [isMobile, table]);

  const reportBulkResult = (
    result: BulkIssueResult,
    verb: "queued" | "skipped",
    failureVerb: "queue" | "skip",
  ) => {
    const { type, message, keep } = describeBulkResult(
      result,
      verb,
      failureVerb,
    );
    addToast({ type, message });
    table.setRowSelection(Object.fromEntries(keep.map((id) => [id, true])));
  };

  const handleBulkQueue = async () => {
    try {
      reportBulkResult(
        await bulkQueueMutation.mutateAsync(selectedIds),
        "queued",
        "queue",
      );
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to queue issues: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleBulkUnqueue = async () => {
    try {
      reportBulkResult(
        await bulkUnqueueMutation.mutateAsync(selectedIds),
        "skipped",
        "skip",
      );
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to skip issues: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleForceSearch = async () => {
    if (window.confirm("Manual search may take several minutes. Continue?")) {
      try {
        const result = await forceSearchMutation.mutateAsync();
        setForceRunId(
          result.status === "partial" ? (result.run_id ?? null) : null,
        );
        addToast({
          type: result.success ? "info" : "error",
          message:
            result.message ||
            result.error ||
            "Search did not start for the wanted issues",
        });
      } catch (err) {
        addToast({
          type: "error",
          message: `Failed to start search: ${err instanceof Error ? err.message : "Unknown error"}`,
        });
      }
    }
  };

  const filtered = tab !== "all" || format !== "all" || filter.trim() !== "";

  const formatCounts = useMemo(() => {
    const manga = issues.filter(
      (issue) => issue.ContentType === "manga",
    ).length;
    return { all: issues.length, comics: issues.length - manga, manga };
  }, [issues]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 flex flex-wrap items-center gap-2 px-4 pt-3 md:px-8">
        {modeBar(formatCounts)}
      </div>
      {!isLoading && !error && (
        <div className="shrink-0 px-4 pt-3 md:px-8">
          <WeekStrip
            issues={issues}
            start={start ?? weekStart(new Date())}
            searchPaused={pausedReason}
          />
        </div>
      )}

      {blockers[0] && (
        <div className="shrink-0 px-4 pt-3 md:px-8">
          <SearchBlockedBanner blocker={blockers[0]} />
        </div>
      )}

      <div className="shrink-0 flex flex-wrap items-center gap-2 px-4 py-3 md:px-8">
        <div
          role="group"
          aria-label="Where it stands"
          className="-mx-4 flex gap-2 overflow-x-auto px-4 md:mx-0 md:px-0"
        >
          {TABS.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={tab === option.value}
              onClick={() => setTab(option.value)}
              className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-control border border-border-subtle px-3 text-[13px] text-foreground-2 hover:text-foreground aria-pressed:border-border-strong aria-pressed:bg-surface-2 aria-pressed:font-medium aria-pressed:text-foreground"
            >
              {option.label}
              <span className="font-mono text-xs text-muted-foreground">
                {counts[option.value]}
              </span>
            </button>
          ))}
        </div>
        <FilterField
          aria-label="Filter releases"
          placeholder="Filter series or publisher"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          widthCap="sm"
        />

        <div className="ml-auto flex items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={() => refetch()}
            disabled={isFetching}
            aria-label="Reload this list"
            title="Reload this list"
          >
            <RefreshCw className={isFetching ? "animate-spin" : ""} />
          </Button>
          {forceRunId && (
            <Button
              type="button"
              variant="outline"
              size="toolbar"
              onClick={async () => {
                try {
                  const result =
                    await retrySearchMutation.mutateAsync(forceRunId);
                  addToast({
                    type: result.success ? "info" : "error",
                    message: result.message || "Queue handoff retry completed",
                  });
                } catch (err) {
                  addToast({
                    type: "error",
                    message: `Retry failed: ${err instanceof Error ? err.message : "Unknown error"}`,
                  });
                }
              }}
              disabled={retrySearchMutation.isPending}
            >
              {retrySearchMutation.isPending
                ? "Retrying…"
                : "Retry queue handoff"}
            </Button>
          )}
          {/* With nothing to search with, the banner's fix is the action. */}
          {!pausedReason && (
            <Button
              type="button"
              variant="outline"
              size="toolbar"
              onClick={handleForceSearch}
              disabled={forceSearchMutation.isPending}
            >
              <Search />
              <span className="max-md:sr-only">Force search</span>
            </Button>
          )}
        </div>
      </div>

      {/* Only the release rows scroll; the filter bar above and the bulk bar
          below stay put. */}
      <div className="flex-1 min-h-0 overflow-auto">
        {isLoading && (
          <div className="px-8 py-4 space-y-2">
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
          </div>
        )}

        {Boolean(error) && (
          <div className="px-8 py-4">
            <ErrorDisplay
              error={error}
              title="Unable to load your releases"
              onRetry={() => refetch()}
            />
          </div>
        )}

        {!isLoading && !error && issues.length === 0 && (
          <EmptyState variant="upcoming" />
        )}

        {!isLoading && !error && issues.length > 0 && rows.length === 0 && (
          <EmptyState
            variant="custom"
            eyebrow="RELEASES · FILTERED"
            title="Nothing matches that filter"
            description={
              filtered
                ? "Pick All or clear the filter to see the whole week."
                : "Nothing to show for this week."
            }
          />
        )}

        {!isLoading && !error && rows.length > 0 && (
          <DataTable
            table={table}
            className="max-md:px-4"
            renderGroupHeader={(row, index, colSpan) => {
              const day = releaseDay(row.original);
              const visible = table.getRowModel().rows;
              if (index > 0 && releaseDay(visible[index - 1].original) === day)
                return null;
              return (
                <tr
                  data-testid="release-day-group"
                  className="border-b border-border-subtle hover:bg-transparent"
                >
                  <td colSpan={colSpan} className="px-2 pt-4 pb-2">
                    <div className="flex items-baseline gap-2 text-[13px]">
                      <span className="font-semibold text-foreground">
                        {day ? dayHeading(day) : "No release date"}
                      </span>
                      <span className="font-mono text-xs text-muted-foreground">
                        {dayCounts.get(day)}
                      </span>
                      {day && isNewComicDay(day) && (
                        <span className="ml-auto text-xs text-muted-foreground">
                          New comic day
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              );
            }}
          />
        )}
      </div>

      <BulkActionBar
        selectedCount={selectedIds.length}
        onMarkWanted={handleBulkQueue}
        onSkip={handleBulkUnqueue}
        onClear={clearSelection}
        isLoading={bulkQueueMutation.isPending || bulkUnqueueMutation.isPending}
      />
      <ReleaseReviewSheet {...reviewSheetProps} />
    </div>
  );
}
