import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Search, RefreshCw } from "lucide-react";
import {
  useUpcoming,
  useForceSearch,
  useBulkQueueIssues,
  useBulkUnqueueIssues,
} from "@/hooks/useQueue";
import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import { useAiStatus } from "@/hooks/useAiStatus";
import { AiSuggestions } from "@/components/weekly/AiSuggestions";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import UpcomingTable from "@/components/queue/UpcomingTable";
import BulkActionBar from "@/components/queue/BulkActionBar";
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
      className="relative px-3 pb-2.5 -mb-px font-mono text-[11px] tracking-[0.1em] uppercase flex items-center gap-2"
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

  const setView = (view: ReleasesView) => {
    setSearchParams({ view });
  };

  return (
    <div className="page-transition -mx-4 sm:-mx-6 lg:-mx-8 -my-8">
      {/* Header */}
      <div className="px-5 py-3.5 border-b border-border flex items-center gap-3">
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
      </div>

      {/* Tab row */}
      <div className="px-5 border-b border-border flex items-end gap-1">
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

      <div className="px-5 py-4">
        {currentView === "mine" ? <MyReleasesView /> : <AllReleasesView />}
      </div>
    </div>
  );
}

function MyReleasesView() {
  const [includeDownloaded, setIncludeDownloaded] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const {
    data: issues = [],
    isLoading,
    error,
    refetch,
  } = useUpcoming(includeDownloaded);
  const forceSearchMutation = useForceSearch();
  const bulkQueueMutation = useBulkQueueIssues();
  const bulkUnqueueMutation = useBulkUnqueueIssues();
  const { addToast } = useToast();

  const handleBulkQueue = async () => {
    try {
      await bulkQueueMutation.mutateAsync(selectedIds);
      addToast({
        type: "success",
        message: `${selectedIds.length} issue${selectedIds.length !== 1 ? "s" : ""} queued`,
      });
      setSelectedIds([]);
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to queue issues: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleBulkUnqueue = async () => {
    try {
      await bulkUnqueueMutation.mutateAsync(selectedIds);
      addToast({
        type: "success",
        message: `${selectedIds.length} issue${selectedIds.length !== 1 ? "s" : ""} skipped`,
      });
      setSelectedIds([]);
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
        await forceSearchMutation.mutateAsync();
        addToast({
          type: "info",
          message: "Search started for all wanted issues",
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
      {/* Controls row */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <div className="font-mono text-[10px] tracking-[0.1em] uppercase text-muted-foreground">
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

        <div className="ml-auto font-mono text-[11px] text-muted-foreground">
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
          <RefreshCw className={`w-3 h-3 ${isLoading ? "animate-spin" : ""}`} />
          refresh
        </button>

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

      {isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
        </div>
      )}

      {error && (
        <ErrorDisplay
          error={error}
          title="Unable to load your releases"
          onRetry={() => refetch()}
        />
      )}

      {!isLoading && !error && issues.length === 0 && (
        <EmptyState variant="upcoming" />
      )}

      {!isLoading && !error && issues.length > 0 && (
        <UpcomingTable issues={issues} onSelectionChange={setSelectedIds} />
      )}

      <BulkActionBar
        selectedCount={selectedIds.length}
        onMarkWanted={handleBulkQueue}
        onSkip={handleBulkUnqueue}
        onClear={() => setSelectedIds([])}
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
        <div className="mb-6">
          <AiSuggestions />
        </div>
      )}

      {isLoading ? (
        <div className="space-y-2">
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
        <div
          className="rounded-[6px] border overflow-hidden"
          style={{ borderColor: "var(--border)" }}
        >
          <div
            className="grid font-mono text-[10px] tracking-[0.1em] uppercase text-muted-foreground px-4 py-2 border-b"
            style={{
              borderColor: "var(--border)",
              background: "var(--card)",
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
                className="grid items-center px-4 py-2 text-[12px] border-b last:border-b-0"
                style={{
                  borderColor: "var(--border-soft, var(--border))",
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
