import { useState } from "react";
import { Search, RefreshCw } from "lucide-react";
import {
  useWanted,
  useForceSearch,
  useBulkUnqueueIssues,
  useSearchWantedIssue,
  describeBulkResult,
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
  const searchWantedIssue = useSearchWantedIssue();
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
      const { type, message, keep } = describeBulkResult(
        await bulkUnqueue.mutateAsync(selectedIds),
        "skipped",
        "skip",
      );
      addToast({ type, message });
      setSelectedIds(keep);
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
        const result = await forceSearch.mutateAsync();
        const withRunReference = (message: string) =>
          result.run_id
            ? `${message}${/[.!?]$/.test(message) ? "" : "."} Run ${result.run_id}.`
            : message;

        if (result.success && result.status === "no_match") {
          addToast({
            type: "info",
            title: "Nothing to search",
            message: withRunReference(
              result.message ||
                "No eligible wanted issues are ready to search.",
            ),
          });
        } else if (
          result.success &&
          (result.status === "accepted" || result.status === undefined)
        ) {
          const accepted = result.accepted;
          const acceptedMessage =
            typeof accepted === "number"
              ? `Search accepted — ${accepted} wanted issue${accepted === 1 ? "" : "s"} queued.`
              : "Search accepted — wanted issues will be processed.";
          addToast({
            type: "info",
            title: "Search accepted",
            message: withRunReference(acceptedMessage),
          });
        } else if (result.success && result.status === "partial") {
          addToast({
            type: "info",
            title: "Search partially accepted",
            message: withRunReference(
              result.message ||
                "Some Wanted issues were queued, but others need attention.",
            ),
          });
        } else if (result.status === "blocked") {
          addToast({
            type: "info",
            title: "Search blocked",
            message:
              result.message ||
              result.error ||
              "Search is blocked until a complete acquisition route is ready.",
          });
        } else {
          addToast({
            type: "error",
            title: "Search failed",
            message:
              result.message || result.error || "Search failed to start.",
          });
        }
      } catch (err) {
        addToast({
          type: "error",
          message: `Failed to start search: ${err instanceof Error ? err.message : "Unknown error"}`,
        });
      }
    }
  };

  const handleSearchSelected = async () => {
    const issueId = selectedIds[0];
    if (!issueId || !window.confirm("Search this one Wanted issue?")) return;
    try {
      const result = await searchWantedIssue.mutateAsync(issueId);
      addToast({
        type: result.success ? "info" : "error",
        title: result.success ? "Search accepted" : "Search failed",
        message:
          result.message || result.error || "Unable to start this search.",
      });
      if (result.success) setSelectedIds([]);
    } catch (err) {
      addToast({
        type: "error",
        message:
          err instanceof Error ? err.message : "Unable to start this search.",
      });
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

      <div className="px-5 py-2.5 border-b border-border flex items-center gap-3">
        <div className="flex-1 max-w-md">
          <FilterField
            placeholder="Filter wanted issues…"
            aria-label="Filter wanted issues"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            shortcut="/"
          />
        </div>
        {searchQuery && (
          <div className="font-mono text-[11px] text-muted-foreground">
            {filteredIssues.length} match
            {filteredIssues.length === 1 ? "" : "es"}
          </div>
        )}
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
            title="Unable to load wanted issues"
            onRetry={() => refetch()}
          />
        </div>
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
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
        />
      )}

      <BulkActionBar
        selectedCount={selectedIds.length}
        onSkip={handleBulkUnqueue}
        onClear={() => setSelectedIds([])}
        onSearch={() => void handleSearchSelected()}
        isLoading={bulkUnqueue.isPending || searchWantedIssue.isPending}
      />
    </div>
  );
}
