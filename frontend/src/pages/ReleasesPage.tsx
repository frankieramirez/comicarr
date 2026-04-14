import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Search, Calendar } from "lucide-react";
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
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import UpcomingTable from "@/components/queue/UpcomingTable";
import FilterBar from "@/components/queue/FilterBar";
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

export default function ReleasesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const viewParam = searchParams.get("view");
  const currentView: ReleasesView = viewParam === "all" ? "all" : "mine";

  const setView = (view: ReleasesView) => {
    setSearchParams({ view });
  };

  return (
    <div className="page-transition">
      <div className="flex items-center gap-3 mb-6">
        <Calendar className="w-6 h-6 text-muted-foreground" />
        <div>
          <h1 className="text-[32px] font-bold tracking-tight">Releases</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {currentView === "mine"
              ? "This week's releases for your library"
              : "This week's new releases industry-wide"}
          </p>
        </div>
      </div>

      {/* View Toggle */}
      <div className="flex gap-2 mb-6">
        <Button
          variant={currentView === "mine" ? "default" : "outline"}
          onClick={() => setView("mine")}
          size="sm"
        >
          My Releases
        </Button>
        <Button
          variant={currentView === "all" ? "default" : "outline"}
          onClick={() => setView("all")}
          size="sm"
        >
          All Releases
        </Button>
      </div>

      {currentView === "mine" ? <MyReleasesView /> : <AllReleasesView />}
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

  const handleClearSelection = () => {
    setSelectedIds([]);
  };

  return (
    <>
      <FilterBar
        showAll={includeDownloaded}
        onToggleFilter={setIncludeDownloaded}
        onRefresh={refetch}
        isRefreshing={isLoading}
      />

      <div className="flex justify-between items-center mb-4">
        <div className="text-sm text-muted-foreground">
          {issues.length} issue{issues.length !== 1 ? "s" : ""} this week
        </div>
        <Button
          onClick={handleForceSearch}
          disabled={forceSearchMutation.isPending}
        >
          <Search className="w-4 h-4 mr-2" />
          Force Search All
        </Button>
      </div>

      {isLoading && (
        <div className="space-y-4">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
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
        onClear={handleClearSelection}
        isLoading={bulkQueueMutation.isPending || bulkUnqueueMutation.isPending}
      />
    </>
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
        <div className="mb-8">
          <AiSuggestions />
        </div>
      )}

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 10 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : !weekly || weekly.length === 0 ? (
        <div className="rounded-lg border border-card-border bg-card p-8 text-center">
          <p className="text-muted-foreground">
            No pull list data available. Run a weekly pull list update from
            Settings.
          </p>
        </div>
      ) : (
        <div className="rounded-lg border border-card-border overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-card-border bg-muted/50">
                <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
                  Title
                </th>
                <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
                  Issue
                </th>
                <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
                  Publisher
                </th>
                <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
                  Status
                </th>
              </tr>
            </thead>
            <tbody>
              {weekly.map((issue, index) => (
                <tr
                  key={`${issue.COMIC}-${issue.ISSUE}-${index}`}
                  className="border-b border-card-border last:border-0 hover:bg-muted/30"
                >
                  <td className="px-4 py-2.5 text-sm font-medium">
                    {issue.COMIC}
                  </td>
                  <td className="px-4 py-2.5 text-sm text-muted-foreground">
                    #{issue.ISSUE}
                  </td>
                  <td className="px-4 py-2.5 text-sm text-muted-foreground">
                    {issue.PUBLISHER}
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full ${
                        issue.STATUS === "Wanted"
                          ? "bg-yellow-500/10 text-yellow-600"
                          : issue.STATUS === "Downloaded"
                            ? "bg-green-500/10 text-green-600"
                            : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {issue.STATUS || "Available"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
