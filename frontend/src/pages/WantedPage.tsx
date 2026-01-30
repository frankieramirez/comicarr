import { useState } from "react";
import { Search } from "lucide-react";
import {
  useWanted,
  useForceSearch,
  useBulkUnqueueIssues,
} from "@/hooks/useQueue";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import WantedTable from "@/components/queue/WantedTable";
import BulkActionBar from "@/components/queue/BulkActionBar";

export default function WantedPage() {
  const [page, setPage] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const limit = 50;
  const offset = page * limit;

  const { data, isLoading, error } = useWanted(limit, offset);
  const issues = data?.issues || [];
  const pagination = data?.pagination;

  const forceSearchMutation = useForceSearch();
  const bulkUnqueueMutation = useBulkUnqueueIssues();
  const { addToast } = useToast();

  // Filter issues by search query (client-side)
  const filteredIssues = searchQuery
    ? issues.filter(
        (issue) =>
          issue.ComicName?.toLowerCase().includes(searchQuery.toLowerCase()) ||
          issue.Issue_Number?.toLowerCase().includes(searchQuery.toLowerCase()),
      )
    : issues;

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

  const handleNextPage = () => {
    setPage((p) => p + 1);
    setSelectedIds([]);
  };

  const handlePrevPage = () => {
    setPage((p) => Math.max(0, p - 1));
    setSelectedIds([]);
  };

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 page-transition">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-foreground mb-2">Wanted Issues</h1>
        <p className="text-muted-foreground">
          {pagination?.total || issues.length} wanted issue
          {(pagination?.total || issues.length) !== 1 ? "s" : ""} in queue
        </p>
      </div>

      <div className="flex items-center justify-between mb-4">
        <Input
          placeholder="Search wanted issues..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="max-w-md"
        />
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
        <div className="text-destructive bg-[var(--status-error-bg)] border border-[var(--status-error)] rounded-lg p-4">
          Error loading wanted issues: {error.message}
        </div>
      )}

      {!isLoading && !error && (
        <WantedTable
          issues={filteredIssues}
          pagination={pagination}
          onNextPage={handleNextPage}
          onPrevPage={handlePrevPage}
          onSelectionChange={setSelectedIds}
        />
      )}

      <BulkActionBar
        selectedCount={selectedIds.length}
        onSkip={handleBulkUnqueue}
        onClear={handleClearSelection}
        isLoading={bulkUnqueueMutation.isPending}
      />
    </div>
  );
}
