import { useState } from "react";
import { Search, RefreshCw } from "lucide-react";
import {
  useWanted,
  useForceSearch,
  useBulkUnqueueIssues,
} from "@/hooks/useQueue";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import WantedTable from "@/components/queue/WantedTable";
import BulkActionBar from "@/components/queue/BulkActionBar";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import PageHeader from "@/components/layout/PageHeader";
import FilterField from "@/components/ui/FilterField";

export default function WantedPage() {
  const [page, setPage] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const limit = 50;
  const offset = page * limit;

  const { data, isLoading, error, refetch } = useWanted(limit, offset);
  const issues = data?.issues || [];
  const pagination = data?.pagination;

  const forceSearch = useForceSearch();
  const bulkUnqueue = useBulkUnqueueIssues();
  const { addToast } = useToast();

  const filteredIssues = searchQuery
    ? issues.filter(
        (i) =>
          i.ComicName?.toLowerCase().includes(searchQuery.toLowerCase()) ||
          i.Issue_Number?.toLowerCase().includes(searchQuery.toLowerCase()),
      )
    : issues;

  const handleBulkUnqueue = async () => {
    try {
      await bulkUnqueue.mutateAsync(selectedIds);
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
        await forceSearch.mutateAsync();
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

  const total = pagination?.total ?? issues.length;

  return (
    <div className="page-transition">
      <PageHeader
        title="Wanted"
        meta={
          isLoading
            ? "loading…"
            : `${total} issue${total === 1 ? "" : "s"} in queue`
        }
        actions={
          <>
            <button
              type="button"
              onClick={() => refetch()}
              disabled={isLoading}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-[5px] border font-mono text-[11px] text-muted-foreground"
              style={{ borderColor: "var(--border)" }}
            >
              <RefreshCw
                className={`w-3 h-3 ${isLoading ? "animate-spin" : ""}`}
              />
              refresh
            </button>
            <button
              type="button"
              onClick={handleForceSearch}
              disabled={forceSearch.isPending}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[5px] text-[12px] font-semibold disabled:opacity-60"
              style={{
                background: "var(--primary)",
                color: "var(--primary-foreground)",
              }}
            >
              <Search className="w-3.5 h-3.5" />
              Force search
            </button>
          </>
        }
      />

      <div className="px-5 py-4">
        <div className="flex items-center gap-3 mb-4">
          <FilterField
            placeholder="Filter wanted issues…"
            aria-label="Filter wanted issues"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            shortcut="/"
          />
          {searchQuery && (
            <div className="font-mono text-[11px] text-muted-foreground">
              {filteredIssues.length} match
              {filteredIssues.length === 1 ? "" : "es"}
            </div>
          )}
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
            title="Unable to load wanted issues"
            onRetry={() => refetch()}
          />
        )}

        {!isLoading && !error && (
          <WantedTable
            issues={filteredIssues}
            pagination={pagination}
            onNextPage={() => {
              setPage((p) => p + 1);
              setSelectedIds([]);
            }}
            onPrevPage={() => {
              setPage((p) => Math.max(0, p - 1));
              setSelectedIds([]);
            }}
            onSelectionChange={setSelectedIds}
          />
        )}
      </div>

      <BulkActionBar
        selectedCount={selectedIds.length}
        onSkip={handleBulkUnqueue}
        onClear={() => setSelectedIds([])}
        isLoading={bulkUnqueue.isPending}
      />
    </div>
  );
}
