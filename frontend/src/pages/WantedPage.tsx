import { ph, plural, t } from "@lingui/core/macro";
import { errorText } from "@/lib/api";
import { Trans } from "@lingui/react/macro";
import { useCallback, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { RefreshCw, Search, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
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
import WantedBySeries from "@/components/queue/WantedBySeries";
import { SEGMENTED_GROUP, SEGMENTED_ITEM } from "@/lib/segmented";
import { useSearchBlockers } from "@/hooks/useAcquisitionHealth";
import { formatNumber } from "@/lib/intl";

export default function WantedPage() {
  const { limit, offset, nextPage, prevPage, resetPage } = useServerPage(50);
  const [searchQuery, setSearchQueryState] = useState("");
  const debouncedSearch = useDebounce(searchQuery, 400);
  const [searchParams, setSearchParams] = useSearchParams();
  // v2: by series is the default; ?view=issue keeps the flat table.
  const view = searchParams.get("view") === "issue" ? "issue" : "series";
  const setView = (next: "series" | "issue") => {
    const params = new URLSearchParams(searchParams);
    if (next === "series") params.delete("view");
    else params.set("view", next);
    setSearchParams(params, { replace: true });
  };
  const [seriesTotals, setSeriesTotals] = useState<{
    issues: number;
    series: number;
  } | null>(null);

  const setSearchQuery = useCallback(
    (value: string) => {
      setSearchQueryState(value);
      resetPage();
    },
    [resetPage],
  );

  const { data, isLoading, isFetching, error, refetch } = useWanted(
    limit,
    offset,
    debouncedSearch,
    { enabled: view === "issue" },
  );
  const issues = data?.issues || [];
  const pagination = data?.pagination;

  const forceSearch = useForceSearch();
  const { pausedReason } = useSearchBlockers();
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
        "skip",
      );
      addToast({ type, message });
      table.setRowSelection(Object.fromEntries(keep.map((id) => [id, true])));
    } catch (err) {
      addToast({
        type: "error",
        message: t`Failed to skip issues: ${ph({ error: errorText(err) })}`,
      });
    }
  };

  const handleForceSearch = async () => {
    if (window.confirm(t`Manual search may take several minutes. Continue?`)) {
      try {
        const result = await forceSearch.mutateAsync();
        const withRunReference = (message: string) => {
          if (!result.run_id) return message;
          const run = result.run_id;
          return /[.!?]$/.test(message)
            ? t`${message} Run ${run}.`
            : t`${message}. Run ${run}.`;
        };

        if (result.success && result.status === "no_match") {
          addToast({
            type: "info",
            title: t`Nothing to search`,
            message: withRunReference(
              result.message ||
                t`No eligible wanted issues are ready to search.`,
            ),
          });
        } else if (
          result.success &&
          (result.status === "accepted" || result.status === undefined)
        ) {
          const accepted = result.accepted;
          const acceptedMessage =
            typeof accepted === "number"
              ? plural(accepted, {
                  one: "Search accepted — # wanted issue queued.",
                  other: "Search accepted — # wanted issues queued.",
                })
              : t`Search accepted — wanted issues will be processed.`;
          addToast({
            type: "info",
            title: t`Search accepted`,
            message: withRunReference(acceptedMessage),
          });
        } else if (result.success && result.status === "partial") {
          addToast({
            type: "info",
            title: t`Search partially accepted`,
            message: withRunReference(
              result.message ||
                t`Some Wanted issues were queued, but others need attention.`,
            ),
          });
        } else if (result.status === "blocked") {
          addToast({
            type: "info",
            title: t`Search blocked`,
            message:
              result.message ||
              result.error ||
              t`Search is blocked until a complete acquisition route is ready.`,
          });
        } else {
          addToast({
            type: "error",
            title: t`Search failed`,
            message:
              result.message || result.error || t`Search failed to start.`,
          });
        }
      } catch (err) {
        addToast({
          type: "error",
          message: t`Failed to start search: ${ph({ error: errorText(err) })}`,
        });
      }
    }
  };

  const handleSearchSelected = async () => {
    const issueId = selectedIds[0];
    if (!issueId || !window.confirm(t`Search this one Wanted issue?`)) return;
    try {
      const result = await searchWantedIssue.mutateAsync(issueId);
      addToast({
        type: result.success ? "info" : "error",
        title: result.success ? t`Search accepted` : t`Search failed`,
        message:
          result.message || result.error || t`Unable to start this search.`,
      });
      if (result.success) clearSelection();
    } catch (err) {
      addToast({
        type: "error",
        message:
          err instanceof Error ? err.message : t`Unable to start this search.`,
      });
    }
  };

  const total = pagination?.total ?? issues.length;
  const isFiltering = Boolean(debouncedSearch.trim());
  const matchCount = isFiltering ? total : null;

  return (
    <div className="page-transition flex h-full min-h-0 flex-col">
      <PageHeader
        title={t`Wanted`}
        meta={
          view === "series"
            ? seriesTotals
              ? t`${ph({ issues: formatNumber(seriesTotals.issues) })} missing in ${ph({ series: formatNumber(seriesTotals.series) })} series`
              : t`loading…`
            : isLoading
              ? t`loading…`
              : plural(total, {
                  one: "# missing issue",
                  other: "# missing issues",
                })
        }
        actions={
          <>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onClick={() => refetch()}
              disabled={isFetching}
              aria-label={t`Refresh`}
              title={t`Refresh`}
            >
              <RefreshCw className={isFetching ? "animate-spin" : ""} />
            </Button>
            <Button variant="ghost" size="toolbar" asChild>
              <Link to="/settings?section=search">
                <SlidersHorizontal />
                <span className="max-md:sr-only">
                  <Trans>Search settings</Trans>
                </span>
              </Link>
            </Button>
            {/* By series, the pacing banner carries "Search now". */}
            {view === "issue" && !pausedReason && (
              <Button
                type="button"
                variant="outline"
                size="toolbar"
                className="bg-surface-2"
                onClick={handleForceSearch}
                disabled={forceSearch.isPending}
              >
                <Search />
                <span className="max-md:sr-only">
                  <Trans>Force search</Trans>
                </span>
              </Button>
            )}
          </>
        }
      />

      <div className="shrink-0 px-4 pb-3 flex items-center gap-3 md:px-8">
        <div className="flex-1 max-w-md">
          <FilterField
            placeholder={
              view === "series"
                ? t`Filter series or issue…`
                : t`Filter wanted issues…`
            }
            aria-label={t`Filter wanted issues`}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            shortcut="/"
          />
        </div>
        {view === "issue" && matchCount !== null && (
          <div className="mono-meta">
            {plural(matchCount, { one: "# match", other: "# matches" })}
          </div>
        )}
        <div
          role="group"
          aria-label={t`Group Wanted`}
          className={`${SEGMENTED_GROUP} ml-auto max-md:hidden`}
        >
          <button
            type="button"
            aria-pressed={view === "series"}
            className={SEGMENTED_ITEM}
            onClick={() => setView("series")}
          >
            <Trans>By series</Trans>
          </button>
          <button
            type="button"
            aria-pressed={view === "issue"}
            className={SEGMENTED_ITEM}
            onClick={() => setView("issue")}
          >
            <Trans>By issue</Trans>
          </button>
        </div>
      </div>

      {view === "series" && (
        <WantedBySeries
          search={debouncedSearch}
          onTotals={setSeriesTotals}
          onSearchNow={() => void handleForceSearch()}
          searching={forceSearch.isPending}
        />
      )}

      {/* Body column — the table owns the scrolling inside it. */}
      {view === "issue" && (
        <div className="flex-1 min-h-0 flex flex-col">
          {isLoading && (
            <div className="px-8 py-4 space-y-2">
              <Skeleton className="h-14" />
              <Skeleton className="h-14" />
              <Skeleton className="h-14" />
            </div>
          )}

          {error && (
            <div className="px-8 py-4">
              <ErrorDisplay
                error={error}
                title={t`Unable to load wanted issues`}
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
      )}

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
