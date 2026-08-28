import { useCallback, useState } from "react";
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
import { useWantedColumns } from "@/components/queue/wantedColumns";
import BulkActionBar from "@/components/queue/BulkActionBar";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import PageHeader from "@/components/layout/PageHeader";
import FilterField from "@/components/ui/FilterField";
import { useServerPage } from "@/components/data-table/useServerPage";
import { useTableState } from "@/components/data-table/useTableState";
import { useDebounce } from "@/hooks/use-debounce";

export default function WantedPage() {
  const { limit, offset, nextPage, prevPage, resetPage } = useServerPage(50);
  const [searchQuery, setSearchQueryState] = useState("");
  const debouncedSearch = useDebounce(searchQuery, 400);

  const setSearchQuery = useCallback(
    (value: string) => {
      setSearchQueryState(value);
      resetPage();
    },
    [resetPage],
  );

  const { data, isLoading, error, refetch } = useWanted(
    limit,
    offset,
    debouncedSearch,
  );
  const issues = data?.issues || [];
  const pagination = data?.pagination;

  const forceSearch = useForceSearch();
  const searchWantedIssue = useSearchWantedIssue();
  const bulkUnqueue = useBulkUnqueueIssues();
  const { addToast } = useToast();

  const columns = useWantedColumns();
  const { table, selectedIds, clearSelection } = useTableState({
    data: issues,
    columns,
    getRowId: (row) => row.IssueID,
    selection: { scope: "filtered" },
    initialSorting: [{ id: "DateAdded", desc: true }],
  });

  const handleBulkUnqueue = async () => {
    try {
      const { type, message, keep } = describeBulkResult(
        await bulkUnqueue.mutateAsync(selectedIds),
        "skipped",
        "skip",
      );
      addToast({ type, message });
      table.setRowSelection(Object.fromEntries(keep.map((id) => [id, true])));
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
      if (result.success) clearSelection();
    } catch (err) {
      addToast({
        type: "error",
        message:
          err instanceof Error ? err.message : "Unable to start this search.",
      });
    }
  };

  const total = pagination?.total ?? issues.length;
  const isFiltering = Boolean(debouncedSearch.trim());
  const matchCount = isFiltering ? total : null;

  return (
    <div className="page-transition flex h-full min-h-0 flex-col">
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

      <div className="shrink-0 px-5 py-2.5 border-b border-border flex items-center gap-3">
        <div className="flex-1 max-w-md">
          <FilterField
            placeholder="Filter wanted issues…"
            aria-label="Filter wanted issues"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            shortcut="/"
          />
        </div>
        {matchCount !== null && (
          <div className="font-mono text-[11px] text-muted-foreground">
            {matchCount} match
            {matchCount === 1 ? "" : "es"}
          </div>
        )}
      </div>

      {/* Body column — the table owns the scrolling inside it. */}
      <div className="flex-1 min-h-0 flex flex-col">
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
            table={table}
            pagination={pagination}
            onNextPage={() => {
              nextPage();
              clearSelection();
            }}
            onPrevPage={() => {
              prevPage();
              clearSelection();
            }}
          />
        )}
      </div>

      <BulkActionBar
        selectedCount={selectedIds.length}
        onSkip={handleBulkUnqueue}
        onClear={clearSelection}
        onSearch={() => void handleSearchSelected()}
        isLoading={bulkUnqueue.isPending || searchWantedIssue.isPending}
      />
    </div>
  );
}
