import { useEffect, useState, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { Search, RefreshCw } from "lucide-react";
import {
  useUpcoming,
  useForceSearch,
  useBulkQueueIssues,
  useBulkUnqueueIssues,
  describeBulkResult,
  type BulkIssueResult,
} from "@/hooks/useQueue";
import { useRetrySearchRun } from "@/hooks/useSeries";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import { useAiStatus } from "@/hooks/useAiStatus";
import { AiSuggestions } from "@/components/weekly/AiSuggestions";
import { useToast } from "@/components/ui/toast";
import { useScheduledJobs, useWeeklyRefresh } from "@/hooks/useWeekly";
import { Skeleton } from "@/components/ui/skeleton";
import UpcomingTable from "@/components/queue/UpcomingTable";
import { useUpcomingColumns } from "@/components/queue/upcomingColumns";
import BulkActionBar from "@/components/queue/BulkActionBar";
import { useTableState } from "@/components/data-table/useTableState";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import EmptyState from "@/components/ui/EmptyState";

interface WeeklyIssue {
  COMIC: string;
  ISSUE: string;
  PUBLISHER: string;
  SHIPDATE: string;
  STATUS: string;
  ComicID: string;
}

function useWeeklyPullList() {
  return useQuery({
    queryKey: ["weekly"],
    queryFn: () => apiRequest<WeeklyIssue[]>("GET", "/api/weekly"),
    staleTime: 5 * 60 * 1000,
  });
}

type ReleasesView = "mine" | "all";

function Tab({
  active,
  label,
  count,
  onClick,
}: {
  active: boolean;
  label: string;
  count?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="relative pb-3 -mb-px font-mono text-[11px] tracking-[0.1em] uppercase flex items-center gap-2"
      style={{
        color: active ? "var(--foreground)" : "var(--muted-foreground)",
      }}
    >
      <span>{label}</span>
      {count !== undefined && (
        <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
          {count}
        </span>
      )}
      <span
        className="absolute left-0 right-0 bottom-0 h-[2px]"
        style={{
          background: active ? "var(--primary)" : "transparent",
        }}
      />
    </button>
  );
}

function ToggleChip({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="font-mono text-[11px] px-2.5 py-1 rounded-full border"
      style={{
        borderColor: active ? "var(--primary)" : "var(--border)",
        color: active ? "var(--primary)" : "var(--muted-foreground)",
        background: active
          ? "color-mix(in oklab, var(--primary) 12%, transparent)"
          : "transparent",
      }}
    >
      {label}
    </button>
  );
}

export default function ReleasesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const viewParam = searchParams.get("view");
  const currentView: ReleasesView = viewParam === "all" ? "all" : "mine";
  const weeklyRefresh = useWeeklyRefresh();
  const queryClient = useQueryClient();
  const [refreshRequested, setRefreshRequested] = useState(false);
  const [refreshObservedActive, setRefreshObservedActive] = useState(false);
  const refreshAccepted = useRef(false);
  const refreshInvalidated = useRef(false);
  const { data: jobs } = useScheduledJobs(refreshRequested);
  const { addToast } = useToast();
  const weeklyJob = jobs?.jobs.find((job) => job.id === "weekly");
  const weeklyStatus = weeklyJob?.status?.toLowerCase();
  const refreshMessage = !refreshRequested
    ? null
    : weeklyStatus === "queued"
      ? "Refresh queued — it will start shortly."
      : weeklyStatus === "running"
        ? "Refreshing releases…"
        : weeklyStatus === "error"
          ? weeklyJob?.last_error ||
            "Refresh failed. Check the pull source, then retry."
          : weeklyStatus === "waiting" && refreshObservedActive
            ? "Releases refreshed."
            : "Refresh queued — it will start shortly.";

  useEffect(() => {
    if (
      !refreshRequested ||
      !refreshAccepted.current ||
      !refreshObservedActive ||
      weeklyStatus !== "waiting" ||
      refreshInvalidated.current
    ) {
      return;
    }
    refreshInvalidated.current = true;
    queryClient.invalidateQueries({ queryKey: ["weekly"] });
    queryClient.invalidateQueries({ queryKey: ["upcoming"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  }, [queryClient, refreshObservedActive, refreshRequested, weeklyStatus]);

  const setView = (view: ReleasesView) => {
    setSearchParams({ view });
  };

  const handleWeeklyRefresh = async () => {
    try {
      const result = await weeklyRefresh.mutateAsync();
      if (result.state === "paused" || (!result.accepted && result.error)) {
        addToast({
          type: "error",
          message:
            result.error ||
            "Weekly refresh is paused. Resume it in Settings, then retry.",
        });
        return;
      }
      refreshAccepted.current = result.accepted;
      refreshInvalidated.current = false;
      setRefreshObservedActive(
        result.state === "queued" || result.state === "running",
      );
      setRefreshRequested(true);
      addToast({
        type: "info",
        message:
          result.message ||
          (result.state === "running"
            ? "Release refresh is already running."
            : "Release refresh queued."),
      });
    } catch (error) {
      addToast({
        type: "error",
        message: `Unable to refresh releases: ${error instanceof Error ? error.message : "Unknown error"}`,
      });
    }
  };

  return (
    <div className="page-transition">
      {/* Header */}
      <div className="px-5 py-3.5 border-b border-border flex items-center justify-between gap-3">
        <div>
          <div className="text-[18px] font-semibold tracking-tight leading-none">
            Releases
          </div>
          <div className="font-mono text-[11px] text-muted-foreground mt-1.5">
            {currentView === "mine"
              ? "this week · your library"
              : "this week · industry-wide"}
          </div>
        </div>
        <button
          type="button"
          onClick={() => void handleWeeklyRefresh()}
          disabled={
            weeklyRefresh.isPending ||
            weeklyStatus === "running" ||
            weeklyStatus === "queued"
          }
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[5px] border text-[12px] font-medium disabled:opacity-50"
          style={{ borderColor: "var(--border)" }}
        >
          <RefreshCw
            className={`w-3.5 h-3.5 ${weeklyRefresh.isPending || weeklyStatus === "running" || weeklyStatus === "queued" ? "animate-spin" : ""}`}
          />
          {weeklyStatus === "running"
            ? "Refreshing…"
            : weeklyStatus === "queued"
              ? "Queued…"
              : "Refresh releases"}
        </button>
      </div>

      {refreshMessage && (
        <div
          role={weeklyStatus === "error" ? "alert" : "status"}
          aria-live={weeklyStatus === "error" ? "assertive" : "polite"}
          className="px-5 py-2 border-b border-border font-mono text-[11px]"
          style={{
            color:
              weeklyStatus === "error"
                ? "var(--status-error)"
                : weeklyStatus === "running"
                  ? "var(--status-active)"
                  : "var(--muted-foreground)",
          }}
        >
          {refreshMessage}
          {weeklyStatus === "error" &&
            " Retry after fixing the pull source connection."}
        </div>
      )}

      {/* Tab row */}
      <div className="px-5 pt-3 border-b border-border flex items-end gap-6">
        <Tab
          active={currentView === "mine"}
          label="Mine"
          onClick={() => setView("mine")}
        />
        <Tab
          active={currentView === "all"}
          label="Industry"
          onClick={() => setView("all")}
        />
      </div>

      <div>
        {currentView === "mine" ? <MyReleasesView /> : <AllReleasesView />}
      </div>
    </div>
  );
}

function MyReleasesView() {
  const [includeDownloaded, setIncludeDownloaded] = useState(false);
  const {
    data: issues = [],
    isLoading,
    error,
    refetch,
  } = useUpcoming(includeDownloaded);
  const forceSearchMutation = useForceSearch();
  const retrySearchMutation = useRetrySearchRun();
  const [forceRunId, setForceRunId] = useState<string | null>(null);
  const bulkQueueMutation = useBulkQueueIssues();
  const bulkUnqueueMutation = useBulkUnqueueIssues();
  const { addToast } = useToast();

  const columns = useUpcomingColumns();
  // Unpaginated: the whole week renders at once, so `pagination` is omitted
  // and the hook holds no page state (#360).
  const { table, selectedIds, clearSelection } = useTableState({
    data: issues,
    columns,
    getRowId: (row) => row.IssueID,
    selection: { scope: "filtered" },
    initialSorting: [{ id: "IssueDate", desc: false }],
  });

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

  return (
    <div>
      {/* Full-width filter bar */}
      <div className="px-5 py-2.5 border-b border-border flex items-center gap-2 flex-wrap">
        <div className="font-mono text-[10px] tracking-[0.1em] uppercase text-muted-foreground/70 pr-1">
          Filter
        </div>
        <ToggleChip
          active={!includeDownloaded}
          label="wanted only"
          onClick={() => setIncludeDownloaded(false)}
        />
        <ToggleChip
          active={includeDownloaded}
          label="include downloaded"
          onClick={() => setIncludeDownloaded(true)}
        />

        <div className="ml-auto flex items-center gap-2">
          <div className="font-mono text-[11px] text-muted-foreground">
            {issues.length} issue{issues.length !== 1 ? "s" : ""}
          </div>

          <button
            type="button"
            onClick={() => refetch()}
            disabled={isLoading}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-[5px] border text-[11px] font-mono"
            style={{
              borderColor: "var(--border)",
              color: "var(--muted-foreground)",
            }}
          >
            <RefreshCw
              className={`w-3 h-3 ${isLoading ? "animate-spin" : ""}`}
            />
            refresh
          </button>
          {forceRunId && (
            <button
              type="button"
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
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-[5px] border text-[11px] font-mono disabled:opacity-60"
              style={{
                borderColor: "var(--border)",
                color: "var(--muted-foreground)",
              }}
            >
              {retrySearchMutation.isPending
                ? "retrying…"
                : "retry queue handoff"}
            </button>
          )}

          <button
            type="button"
            onClick={handleForceSearch}
            disabled={forceSearchMutation.isPending}
            className="inline-flex items-center gap-1.5 px-3 py-1 rounded-[5px] text-[12px] font-semibold disabled:opacity-60"
            style={{
              background: "var(--primary)",
              color: "var(--primary-foreground)",
            }}
          >
            <Search className="w-3.5 h-3.5" />
            Force search
          </button>
        </div>
      </div>

      {isLoading && (
        <div className="px-5 py-4 space-y-2">
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
        </div>
      )}

      {error && (
        <div className="px-5 py-4">
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

      {!isLoading && !error && issues.length > 0 && (
        <UpcomingTable table={table} />
      )}

      <BulkActionBar
        selectedCount={selectedIds.length}
        onMarkWanted={handleBulkQueue}
        onSkip={handleBulkUnqueue}
        onClear={clearSelection}
        isLoading={bulkQueueMutation.isPending || bulkUnqueueMutation.isPending}
      />
    </div>
  );
}

function AllReleasesView() {
  const { data: weekly, isLoading, error, refetch } = useWeeklyPullList();
  const { data: aiStatus } = useAiStatus();

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
    <>
      {aiStatus?.configured && (
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
      ) : !weekly || weekly.length === 0 ? (
        <EmptyState
          variant="custom"
          eyebrow="PULL LIST · EMPTY"
          title="No pull list data"
          description="Run a weekly pull list update from Settings to populate this view."
        />
      ) : (
        <div>
          <div
            className="grid font-mono text-[10px] tracking-[0.1em] uppercase text-muted-foreground/70 px-5 py-2 border-b bg-muted/30"
            style={{
              borderColor: "var(--border)",
              gridTemplateColumns: "1fr 80px 160px 100px",
            }}
          >
            <div>title</div>
            <div>issue</div>
            <div>publisher</div>
            <div>status</div>
          </div>
          {weekly.map((issue, index) => {
            const status = issue.STATUS || "Available";
            const statusColor =
              status === "Wanted"
                ? "var(--primary)"
                : status === "Downloaded"
                  ? "var(--status-active)"
                  : "var(--muted-foreground)";
            return (
              <div
                key={`${issue.COMIC}-${issue.ISSUE}-${index}`}
                className="grid items-center px-5 py-2 text-[12px] border-b border-border/50"
                style={{
                  gridTemplateColumns: "1fr 80px 160px 100px",
                }}
              >
                <div className="font-medium truncate">{issue.COMIC}</div>
                <div className="font-mono text-[11px] text-muted-foreground">
                  #{issue.ISSUE}
                </div>
                <div className="text-muted-foreground truncate">
                  {issue.PUBLISHER}
                </div>
                <div className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase">
                  <span
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ background: statusColor }}
                  />
                  <span style={{ color: statusColor }}>{status}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
