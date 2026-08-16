import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  createColumnHelper,
  type RowSelectionState,
  type SortingState,
} from "@tanstack/react-table";
import { useQueryStates, parseAsStringLiteral } from "nuqs";
import {
  Trash2,
  Pause,
  Play,
  X,
  LayoutList,
  LayoutGrid,
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
  ImageOff,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import EmptyState from "@/components/ui/EmptyState";
import FilterField from "@/components/ui/FilterField";
import SeriesFilters, {
  type TypeFilter,
  type ProgressFilter,
  type StatusFilter,
} from "./SeriesFilters";
import SeriesGrid from "./SeriesGrid";
import {
  getIsAllSelected,
  toggleAllSelected,
  useTableState,
  type ComicarrRow,
  type ComicarrTableFeatures,
  type TableStore,
} from "@/components/data-table/useTableState";
import { DataTableFooter } from "@/components/data-table/DataTableFooter";
import { useTableUrlStore } from "@/components/data-table/tableUrlStore";
import {
  getProgressPercentage,
  getProgressCategory,
  seriesCoverSrc,
} from "@/lib/series-utils";
import {
  useBulkDeleteSeries,
  useBulkPauseSeries,
  useBulkResumeSeries,
} from "@/hooks/useSeries";
import { useToast } from "@/components/ui/toast";
import type { Comic } from "@/types";

const columnHelper = createColumnHelper<ComicarrTableFeatures, Comic>();

// Domain filters and the view toggle only. `page`, `sort` and `search` are the
// table's own state and live in the shared URL store (tableUrlStore.ts) under
// the same keys as before, so existing bookmarks survive (#377).
const seriesParams = {
  type: parseAsStringLiteral(["comic", "manga"] as const),
  progress: parseAsStringLiteral(["0", "partial", "100"] as const),
  status: parseAsStringLiteral(["Active", "Paused", "Ended"] as const),
  view: parseAsStringLiteral(["list", "grid"] as const).withDefault("list"),
};

// List row tracks. Phone widths only keep checkbox / cover / title so the
// title track always receives free space (#414). Desktop keeps the full row.
// Title floor on md+ is minmax(10rem, 1fr) so truncate never collapses to 0px
// beside fixed secondary columns.
const LIST_ROW_COLS =
  "grid-cols-[20px_40px_minmax(0,1fr)] md:grid-cols-[20px_40px_minmax(10rem,1fr)_160px_100px_110px_180px_60px]";

/** Secondary desktop-only columns — removed from the grid on phone widths.
 *  `max-md:hidden` leaves the element's own display (block/flex/inline-flex)
 *  intact at md+, unlike `hidden md:block` which fights flex utilities. */
const DESKTOP_COL = "max-md:hidden";

interface SeriesTableProps {
  data?: Comic[];
  isLoading?: boolean;
}

export default function SeriesTable({
  data = [],
  isLoading,
}: SeriesTableProps) {
  const navigate = useNavigate();
  const [params, setParams] = useQueryStates(seriesParams, {
    history: "replace",
  });
  const [confirmDeleteFor, setConfirmDeleteFor] =
    useState<RowSelectionState | null>(null);

  const bulkDeleteMutation = useBulkDeleteSeries();
  const bulkPauseMutation = useBulkPauseSeries();
  const bulkResumeMutation = useBulkResumeSeries();
  const { addToast } = useToast();

  const typeFilter: TypeFilter = params.type ?? "all";
  const progressFilter: ProgressFilter = params.progress ?? "all";
  const statusFilter: StatusFilter = params.status ?? "all";

  const isGridView = params.view === "grid";
  const pageSize = isGridView ? 24 : 20;

  const filteredData = useMemo(() => {
    return data.filter((comic) => {
      if (typeFilter !== "all") {
        const contentType = comic.ContentType?.toLowerCase();
        if (typeFilter === "manga" && contentType !== "manga") return false;
        if (typeFilter === "comic" && contentType === "manga") return false;
      }
      if (progressFilter !== "all") {
        if (getProgressCategory(comic) !== progressFilter) return false;
      }
      if (statusFilter !== "all") {
        if (comic.Status !== statusFilter) return false;
      }
      return true;
    });
  }, [data, typeFilter, progressFilter, statusFilter]);

  // Columns are only used by TanStack for sorting & filtering state; rendering
  // is done inline below to match the compact grid design.
  const columns = useMemo(
    () =>
      columnHelper.columns([
        columnHelper.accessor("ComicName", { id: "ComicName" }),
        columnHelper.accessor("ComicPublisher", { id: "ComicPublisher" }),
        columnHelper.accessor("Status", { id: "Status" }),
        columnHelper.accessor("ComicYear", { id: "ComicYear" }),
      ]),
    [],
  );

  const urlStore = useTableUrlStore({ history: "replace" });
  const search = urlStore.state.globalFilter;

  // The clamp has to count the rows TanStack will actually paginate, and the
  // global search runs inside the hook — after this clamp is already fixed —
  // so the search is reproduced here: TanStack's `includesString`
  // (case-insensitive substring per column value) over the same four accessor
  // columns. The deep-link test pins a searched out-of-range page so drift
  // between the two surfaces as a failure, not an empty table.
  const searchedCount = useMemo(() => {
    if (!search) return filteredData.length;
    const query = search.toLowerCase();
    return filteredData.filter((comic) =>
      [
        comic.ComicName,
        comic.ComicPublisher,
        comic.Status,
        comic.ComicYear,
      ].some((value) => value?.toString().toLowerCase().includes(query)),
    ).length;
  }, [filteredData, search]);

  // The render-time, display-only clamp that replaced the page-clamp effect
  // (#360): an out-of-range `pageIndex` renders the last real page and the URL
  // is never rewritten — "rows have not arrived yet" and "genuinely out of
  // range" are the same code path here, and the rewrite that tried to tell
  // them apart was the deep-link bug (#372, #381). The clamp composes over the
  // URL store because the hook feeds `store.state.pageIndex` straight to
  // TanStack, which renders an empty page for an index past the end.
  const maxPage = Math.max(0, Math.ceil(searchedCount / pageSize) - 1);
  const pageIndex = Math.min(urlStore.state.pageIndex, maxPage);
  const store = useMemo<TableStore>(
    () => ({
      state: { ...urlStore.state, pageIndex },
      setState: urlStore.setState,
    }),
    [urlStore, pageIndex],
  );

  const pagination = useMemo(() => ({ pageSize }), [pageSize]);

  const {
    table,
    selectedIds: selectedSeriesIds,
    clearSelection,
  } = useTableState({
    data: filteredData,
    columns,
    getRowId: (row) => row.ComicID,
    pagination,
    // The one page-scoped select-all left (#382); "filtered" would change what
    // the header checkbox selects.
    selection: { scope: "page" },
    store,
  });

  const sorting = table.state.sorting;
  const effectivePage = table.state.pagination.pageIndex;

  // A selection change must invalidate an armed delete confirmation. That
  // reset used to live in `onRowSelectionChange`, which the hook now owns, so
  // it is derived instead: the confirmation is armed against the selection
  // state *object*, and every selection change (including the hook's pruning)
  // produces a new one, disarming it.
  const rowSelection = table.state.rowSelection;
  const confirmDelete =
    confirmDeleteFor !== null && confirmDeleteFor === rowSelection;

  const handleBulkDelete = async () => {
    if (!confirmDelete) {
      setConfirmDeleteFor(rowSelection);
      return;
    }
    try {
      await bulkDeleteMutation.mutateAsync(selectedSeriesIds);
      addToast({
        type: "success",
        message: `${selectedSeriesIds.length} series deleted`,
      });
      clearSelection();
      setConfirmDeleteFor(null);
    } catch {
      addToast({
        type: "error",
        title: "Error",
        description: "Failed to delete series",
      });
    }
  };

  const handleBulkPause = async () => {
    try {
      await bulkPauseMutation.mutateAsync(selectedSeriesIds);
      addToast({
        type: "success",
        message: `${selectedSeriesIds.length} series paused`,
      });
      clearSelection();
    } catch {
      addToast({
        type: "error",
        title: "Error",
        description: "Failed to pause series",
      });
    }
  };

  const handleBulkResume = async () => {
    try {
      await bulkResumeMutation.mutateAsync(selectedSeriesIds);
      addToast({
        type: "success",
        message: `${selectedSeriesIds.length} series resumed`,
      });
      clearSelection();
    } catch {
      addToast({
        type: "error",
        title: "Error",
        description: "Failed to resume series",
      });
    }
  };

  const pageCount = table.getPageCount();
  const pageRows = table.getRowModel().rows;
  const totalFiltered = table.getFilteredRowModel().rows.length;

  const currentSort = sorting[0];
  const sortLabel = currentSort
    ? `${columnIdToLabel(currentSort.id)} ${currentSort.desc ? "↓" : "↑"}`
    : undefined;

  const toggleSort = (columnId: string) => {
    const existing = sorting[0];
    let next: SortingState;
    if (!existing || existing.id !== columnId) {
      next = [{ id: columnId, desc: false }];
    } else if (!existing.desc) {
      next = [{ id: columnId, desc: true }];
    } else {
      next = [];
    }
    // No explicit page reset: the sorted row model recomputing fires TanStack's
    // `autoResetPageIndex`, and its microtask drains before nuqs' flush, so the
    // sort write and the page reset are still one URL write (#360, #377).
    table.setSorting(next);
  };

  if (isLoading) {
    return (
      <div className="px-5 py-4">
        <div className="space-y-3">
          {isGridView ? (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
              {[...Array(12)].map((_, i) => (
                <div key={i} className="space-y-2">
                  <Skeleton className="aspect-[2/3] w-full rounded-lg" />
                  <Skeleton className="h-4 w-3/4" />
                  <Skeleton className="h-3 w-1/2" />
                </div>
              ))}
            </div>
          ) : (
            [...Array(10)].map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))
          )}
        </div>
      </div>
    );
  }

  if (data.length === 0) {
    return <EmptyState variant="library" />;
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Unified action bar: view · search · filters · results */}
      <div className="shrink-0 px-5 py-2 border-b border-border flex flex-wrap items-center gap-2 min-h-[44px]">
        <div className="inline-flex shrink-0 rounded-md border border-border overflow-hidden">
          <button
            type="button"
            onClick={() => {
              // The page-size change resets the page inside the hook — the one
              // reset auto-reset provably misses (#360).
              setParams({ view: null });
              clearSelection();
            }}
            className={`px-2 py-1.5 transition-colors ${
              !isGridView
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
            aria-label="List view"
          >
            <LayoutList className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => {
              setParams({ view: "grid" });
              clearSelection();
            }}
            className={`px-2 py-1.5 border-l border-border transition-colors ${
              isGridView
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
            aria-label="Grid view"
          >
            <LayoutGrid className="w-3.5 h-3.5" />
          </button>
        </div>

        <div className="w-[min(220px,100%)] sm:w-[220px] shrink-0">
          <FilterField
            type="search"
            placeholder="Filter series…"
            aria-label="Filter series"
            shortcut="/"
            widthCap="full"
            value={search}
            onChange={(e) => table.setGlobalFilter(e.target.value)}
          />
        </div>

        <div className="flex-1 min-w-0">
          <SeriesFilters
            typeFilter={typeFilter}
            progressFilter={progressFilter}
            statusFilter={statusFilter}
            onTypeChange={(value) =>
              setParams({ type: value === "all" ? null : value })
            }
            onProgressChange={(value) =>
              setParams({ progress: value === "all" ? null : value })
            }
            onStatusChange={(value) =>
              setParams({ status: value === "all" ? null : value })
            }
            resultCount={totalFiltered}
            sortLabel={sortLabel}
          />
        </div>
      </div>

      {/* Bulk action bar */}
      {!isGridView && selectedSeriesIds.length > 0 && (
        <div className="shrink-0 px-5 py-2 border-b border-border flex items-center gap-3 bg-primary/5">
          <span className="text-xs font-medium">
            {selectedSeriesIds.length} selected
          </span>
          <Button
            size="sm"
            variant="destructive"
            onClick={handleBulkDelete}
            disabled={bulkDeleteMutation.isPending}
            className="h-7 text-xs"
          >
            <Trash2 className="w-3 h-3 mr-1" />
            {confirmDelete ? "Confirm Delete" : "Delete"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={handleBulkPause}
            disabled={bulkPauseMutation.isPending}
            className="h-7 text-xs"
          >
            <Pause className="w-3 h-3 mr-1" />
            Pause
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={handleBulkResume}
            disabled={bulkResumeMutation.isPending}
            className="h-7 text-xs"
          >
            <Play className="w-3 h-3 mr-1" />
            Resume
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              clearSelection();
              setConfirmDeleteFor(null);
            }}
            className="h-7 text-xs ml-auto"
          >
            <X className="w-3 h-3 mr-1" />
            Clear
          </Button>
        </div>
      )}

      {/* Body */}
      {isGridView ? (
        <div className="flex-1 min-h-0 overflow-auto px-5 py-4">
          <SeriesGrid
            rows={pageRows}
            onCardClick={(comic) => navigate(`/library/${comic.ComicID}`)}
          />
        </div>
      ) : (
        <div className="flex-1 min-h-0 overflow-auto">
          {/* min-width only on md+: phone list is a 3-col adaptive row, not a
              squeezed desktop table that collapses the title track (#414). */}
          <div className="flex flex-col min-h-full md:min-w-[820px]">
            <div
              className={`sticky top-0 z-10 px-5 py-2 grid items-center gap-3 border-b border-border bg-muted/30 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70 ${LIST_ROW_COLS}`}
            >
              <Checkbox
                aria-label="Select all series on page"
                checked={getIsAllSelected(table)}
                onCheckedChange={(value) => toggleAllSelected(table, !!value)}
              />
              <span />
              <SortHeader
                label="title"
                active={sorting[0]?.id === "ComicName"}
                desc={sorting[0]?.id === "ComicName" && sorting[0].desc}
                onClick={() => toggleSort("ComicName")}
              />
              <div className={DESKTOP_COL}>
                <SortHeader
                  label="publisher"
                  active={sorting[0]?.id === "ComicPublisher"}
                  desc={sorting[0]?.id === "ComicPublisher" && sorting[0].desc}
                  onClick={() => toggleSort("ComicPublisher")}
                />
              </div>
              <div className={DESKTOP_COL}>
                <SortHeader
                  label="status"
                  active={sorting[0]?.id === "Status"}
                  desc={sorting[0]?.id === "Status" && sorting[0].desc}
                  onClick={() => toggleSort("Status")}
                />
              </div>
              <span className={DESKTOP_COL}>issues</span>
              <span className={DESKTOP_COL}>progress</span>
              <span className={`${DESKTOP_COL} text-right`}>
                <SortHeader
                  label="yr"
                  active={sorting[0]?.id === "ComicYear"}
                  desc={sorting[0]?.id === "ComicYear" && sorting[0].desc}
                  onClick={() => toggleSort("ComicYear")}
                  align="right"
                />
              </span>
            </div>

            <div className="flex-1">
              {pageRows.length === 0 ? (
                <div className="px-5 py-10 text-center text-sm text-muted-foreground">
                  No results.
                </div>
              ) : (
                pageRows.map((row) => (
                  <SeriesRow
                    key={row.id}
                    row={row}
                    onClick={() => navigate(`/library/${row.original.ComicID}`)}
                  />
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* Footer — a sibling of the scroll region rather than a sticky child, so
          it sits on the bottom edge of the viewport for both views and does not
          ride the list's horizontal scroll. */}
      <DataTableFooter
        start={pageRows.length === 0 ? 0 : effectivePage * pageSize + 1}
        end={effectivePage * pageSize + pageRows.length}
        total={totalFiltered}
        page={effectivePage + 1}
        pageCount={pageCount}
        onPrevPage={() => table.previousPage()}
        onNextPage={() => table.nextPage()}
        notes={
          selectedSeriesIds.length > 0
            ? `${selectedSeriesIds.length} selected`
            : undefined
        }
      />
    </div>
  );
}

function columnIdToLabel(id: string): string {
  switch (id) {
    case "ComicName":
      return "title";
    case "ComicPublisher":
      return "publisher";
    case "Status":
      return "status";
    case "ComicYear":
      return "year";
    default:
      return id;
  }
}

interface SortHeaderProps {
  label: string;
  active: boolean;
  desc: boolean | "" | undefined;
  onClick: () => void;
  align?: "left" | "right";
}

function SortHeader({
  label,
  active,
  desc,
  onClick,
  align = "left",
}: SortHeaderProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1 hover:text-foreground ${
        align === "right" ? "flex-row-reverse" : ""
      } ${active ? "text-foreground" : ""}`}
    >
      <span>{label}</span>
      {active ? (
        desc ? (
          <ChevronDown className="w-3 h-3" />
        ) : (
          <ChevronUp className="w-3 h-3" />
        )
      ) : (
        <ChevronsUpDown className="w-3 h-3 opacity-40" />
      )}
    </button>
  );
}

interface SeriesRowProps {
  row: ComicarrRow<Comic>;
  onClick: () => void;
}

function SeriesRow({ row, onClick }: SeriesRowProps) {
  const comic = row.original;
  const isManga = comic.ContentType?.toLowerCase() === "manga";
  const kindLabel = isManga ? "MANGA" : "COMIC";
  const have = parseInt(String(comic.Have)) || 0;
  const total = parseInt(String(comic.Total)) || 0;
  const progress = getProgressPercentage(comic);
  const status = (comic.Status || "").toLowerCase();
  const statusColor = statusTextColor(status);
  const isSelected = row.getIsSelected();

  // Phone rows fold secondary metadata under the title so the primary
  // identifier stays readable without horizontal scroll (#414).
  const mobileMeta = [
    comic.ComicPublisher,
    comic.ComicYear ? `(${comic.ComicYear})` : null,
    total > 0 ? `${have}/${total}` : null,
    status || null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      onClick={onClick}
      data-series-row
      className={`px-5 py-2 grid items-center gap-3 border-b border-border/50 text-[12.5px] cursor-pointer transition-colors ${LIST_ROW_COLS} ${
        isSelected ? "bg-primary/10" : "hover:bg-muted/40"
      }`}
    >
      <div onClick={(e) => e.stopPropagation()}>
        <Checkbox
          aria-label={`Select ${comic.ComicName}`}
          checked={isSelected}
          onCheckedChange={(value) => row.toggleSelected(!!value)}
        />
      </div>

      <CoverThumb comicId={comic.ComicID} alt={comic.ComicName} />

      <div className="min-w-0" data-series-title-slot>
        <div className="flex min-w-0 items-center gap-2">
          {/* flex-1 + min-w-0 keeps the title the flexible primary and stops
              the kind badge from starving truncate to 0px width (#414). */}
          <span
            data-testid="series-row-title"
            className="min-w-0 flex-1 truncate font-medium"
          >
            {comic.ComicName}
          </span>
          <span className="font-mono text-[9px] text-muted-foreground/70 px-1 py-[1px] border border-border rounded-[3px] uppercase tracking-wider shrink-0">
            {kindLabel}
          </span>
        </div>
        {mobileMeta ? (
          <div className="mt-0.5 truncate text-[11px] text-muted-foreground md:hidden">
            {mobileMeta}
          </div>
        ) : null}
        {comic.ComicYear ? (
          <div className="mt-0.5 hidden text-[11px] text-muted-foreground md:block">
            ({comic.ComicYear})
          </div>
        ) : null}
      </div>

      <div className={`${DESKTOP_COL} text-muted-foreground truncate`}>
        {comic.ComicPublisher || "—"}
      </div>

      <div
        className={`${DESKTOP_COL} inline-flex items-center gap-1.5 font-mono text-[10px]`}
        style={{ color: statusColor }}
      >
        <span
          className="inline-block w-1.5 h-1.5 rounded-full"
          style={{ background: statusColor }}
        />
        {status || "unknown"}
      </div>

      <div className={`${DESKTOP_COL} font-mono text-[12px] tabular-nums`}>
        <span>{have}</span>
        <span className="text-muted-foreground/60">/{total}</span>
      </div>

      <div className={`${DESKTOP_COL} flex items-center gap-2`}>
        <div className="flex-1 h-1 bg-border rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${progress}%`,
              background:
                progress === 100
                  ? "var(--status-active, #22c55e)"
                  : "var(--primary)",
            }}
          />
        </div>
        <span className="font-mono text-[10px] text-muted-foreground w-7 text-right tabular-nums">
          {progress}
        </span>
      </div>

      <div
        className={`${DESKTOP_COL} font-mono text-[11px] text-muted-foreground/70 text-right`}
      >
        {comic.ComicYear || "—"}
      </div>
    </div>
  );
}

function statusTextColor(status: string): string {
  switch (status) {
    case "active":
      return "var(--status-active, #22c55e)";
    case "paused":
      return "var(--status-paused, #f59e0b)";
    case "ended":
      return "var(--status-ended, #6b7280)";
    default:
      return "var(--muted-foreground)";
  }
}

interface CoverThumbProps {
  comicId?: string | null;
  alt?: string;
}

function CoverThumb({ comicId, alt }: CoverThumbProps) {
  const src = seriesCoverSrc(comicId);
  const [erroredSrc, setErroredSrc] = useState<string | null>(null);
  const errored = erroredSrc !== null && erroredSrc === src;

  return (
    <div className="w-[32px] h-[44px] bg-muted rounded-sm overflow-hidden flex-shrink-0">
      {src && !errored ? (
        <img
          src={src}
          alt={alt || ""}
          className="w-full h-full object-cover"
          loading="lazy"
          onError={() => setErroredSrc(src)}
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-muted-foreground/40">
          <ImageOff className="w-3 h-3" />
        </div>
      )}
    </div>
  );
}
