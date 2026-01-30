import { useState } from "react";
import { Search } from "lucide-react";
import {
  useUpcoming,
  useForceSearch,
  useBulkQueueIssues,
  useBulkUnqueueIssues,
} from "@/hooks/useQueue";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import UpcomingTable from "@/components/queue/UpcomingTable";
import FilterBar from "@/components/queue/FilterBar";
import BulkActionBar from "@/components/queue/BulkActionBar";

export default function UpcomingPage() {
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
    <div className="max-w-7xl mx-auto px-4 py-6 page-transition">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">
          Upcoming Releases
        </h1>
        <p className="text-gray-600">This week's releases</p>
      </div>

      <FilterBar
        showAll={includeDownloaded}
        onToggleFilter={setIncludeDownloaded}
        onRefresh={refetch}
        isRefreshing={isLoading}
      />

      <div className="flex justify-between items-center mb-4">
        <div className="text-sm text-gray-600">
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
        <div className="text-red-600 bg-red-50 border border-red-200 rounded-lg p-4">
          Error loading upcoming releases: {error.message}
        </div>
      )}

      {!isLoading && !error && (
        <UpcomingTable issues={issues} onSelectionChange={setSelectedIds} />
      )}

      <BulkActionBar
        selectedCount={selectedIds.length}
        onMarkWanted={handleBulkQueue}
        onSkip={handleBulkUnqueue}
        onClear={handleClearSelection}
        isLoading={bulkQueueMutation.isPending || bulkUnqueueMutation.isPending}
      />
    </div>
  );
}
