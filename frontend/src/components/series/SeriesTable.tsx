import { SEGMENTED_GROUP, SEGMENTED_ITEM } from "@/lib/segmented";
import { useState, useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
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
import StatusBadge from "@/components/StatusBadge";
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
import { DESKTOP_COL } from "@/components/data-table/gridColumns";
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

const LIBRARY_VIEW_KEY = "comicarr-library-view";

const seriesParams = {
  type: parseAsStringLiteral(["comic", "manga", "magazine"] as const),
  progress: parseAsStringLiteral(["0", "partial", "100"] as const),
  status: parseAsStringLiteral(["Active", "Paused", "Ended"] as const),
  view: parseAsStringLiteral(["list", "grid"] as const),
};

/** Each series is exactly one kind; anything unrecognized is a comic. */
function seriesKindOf(comic: Comic): "comic" | "manga" | "magazine" {
  const contentType = comic.ContentType?.toLowerCase();
  return contentType === "manga" || contentType === "magazine"
    ? contentType
    : "comic";
}

const LIST_ROW_COLS =
  "grid-cols-[20px_40px_minmax(0,1fr)] md:grid-cols-[20px_40px_minmax(10rem,1fr)_160px_100px_110px_180px_60px]";

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

  let savedView: "grid" | "list" = "list";
  try {
    savedView =
      localStorage.getItem(LIBRARY_VIEW_KEY) === "grid" ? "grid" : "list";
  } catch {
    // Blocked storage falls back to list.
  }
  const isGridView = (params.view ?? savedView) === "grid";
  const pageSize = isGridView ? 24 : 20;

  const hasMagazines = useMemo(
    () => data.some((comic) => seriesKindOf(comic) === "magazine"),
    [data],
  );

  const typeCounts = useMemo(() => {
    const counts: Partial<Record<TypeFilter, number>> = { all: data.length };
    for (const comic of data) {
      const kind = seriesKindOf(comic) as TypeFilter;
      counts[kind] = (counts[kind] ?? 0) + 1;
    }
    return counts;
  }, [data]);

  const filteredData = useMemo(() => {
    return data.filter((comic) => {
      if (typeFilter !== "all" && seriesKindOf(comic) !== typeFilter) {
        return false;
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
    selection: { scope: "page" },
    store,
  });

  const sorting = table.state.sorting;
  const effectivePage = table.state.pagination.pageIndex;

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
    table.setSorting(next);
  };

  if (isLoading) {
    return (
      <div className="px-8 py-4">
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
      {/* Unified action bar: kind · search · filters · results · view */}
      <div className="shrink-0 px-8 pb-3 flex flex-wrap items-center gap-2">
        <div className="order-2 w-[min(240px,100%)] sm:w-[240px] shrink-0">
          <FilterField
            type="search"
            placeholder="Filter series"
            aria-label="Filter series"
            shortcut="/"
            widthCap="full"
            value={search}
            onChange={(e) => table.setGlobalFilter(e.target.value)}
          />
        </div>

        <div className="contents">
          <SeriesFilters
            hasMagazines={hasMagazines}
            typeFilter={typeFilter}
            progressFilter={progressFilter}
            statusFilter={statusFilter}
            typeCounts={typeCounts}
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

        <div
          role="group"
          aria-label="View"
          className={`order-4 shrink-0 ${SEGMENTED_GROUP}`}
        >
          {(
            [
              ["grid", "Grid", LayoutGrid],
              ["list", "List", LayoutList],
            ] as const
          ).map(([value, label, Icon]) => {
            const pressed = value === "grid" ? isGridView : !isGridView;
            return (
              <button
                key={value}
                type="button"
                onClick={() => {
                  try {
                    localStorage.setItem(LIBRARY_VIEW_KEY, value);
                  } catch {
                    // Blocked storage must not stop the view change.
                  }
                  setParams({ view: value === "grid" ? "grid" : null });
                  clearSelection();
                }}
                className={SEGMENTED_ITEM}
                aria-label={`${label} view`}
                aria-pressed={pressed}
              >
                <Icon className="size-3.5" aria-hidden="true" />
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Bulk action bar */}
      {!isGridView && selectedSeriesIds.length > 0 && (
        <div className="shrink-0 mx-8 mb-2 px-3 py-1.5 rounded-md border border-border-subtle bg-surface-1 flex items-center gap-3">
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
        <div className="flex-1 min-h-0 overflow-auto px-8 pb-6 pt-1">
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
              className={`sticky top-0 z-10 mx-8 px-2 h-8 grid items-center gap-3 border-b border-border-subtle bg-background text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground ${LIST_ROW_COLS}`}
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
                  label="year"
                  active={sorting[0]?.id === "ComicYear"}
                  desc={sorting[0]?.id === "ComicYear" && sorting[0].desc}
                  onClick={() => toggleSort("ComicYear")}
                  align="right"
                />
              </span>
            </div>

            <div className="flex-1">
              {pageRows.length === 0 ? (
                <div className="px-8 py-10 text-center text-sm text-muted-foreground">
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
  const sortAnnouncement = active
    ? desc
      ? "sorted descending"
      : "sorted ascending"
    : null;
  return (
    <button
      type="button"
      onClick={onClick}
      className={`group/sort inline-flex items-center gap-1 uppercase tracking-[0.04em] hover:text-foreground ${
        align === "right" ? "flex-row-reverse" : ""
      } ${active ? "text-foreground" : ""}`}
    >
      <span>{label}</span>
      {active ? (
        desc ? (
          <ChevronDown className="w-3 h-3" aria-hidden />
        ) : (
          <ChevronUp className="w-3 h-3" aria-hidden />
        )
      ) : (
        <ChevronsUpDown
          className="w-3 h-3 opacity-0 transition-opacity group-hover/sort:opacity-60"
          aria-hidden
        />
      )}
      {sortAnnouncement ? (
        <span className="sr-only">{sortAnnouncement}</span>
      ) : null}
    </button>
  );
}

interface SeriesRowProps {
  row: ComicarrRow<Comic>;
  onClick: () => void;
}

function SeriesRow({ row, onClick }: SeriesRowProps) {
  const comic = row.original;
  const kindLabel = seriesKindOf(comic).toUpperCase();
  const have = parseInt(String(comic.Have)) || 0;
  const total = parseInt(String(comic.Total)) || 0;
  const progress = getProgressPercentage(comic);
  const status = (comic.Status || "").toLowerCase();
  const isSelected = row.getIsSelected();

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
      className={`mx-8 px-2 py-1.5 grid items-center gap-3 border-b border-border-subtle text-[13px] cursor-pointer transition-colors ${LIST_ROW_COLS} ${
        isSelected ? "bg-selection" : "hover:bg-surface-1"
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
          <Link
            to={`/library/${comic.ComicID}`}
            data-testid="series-row-title"
            className="min-w-0 flex-1 truncate font-medium hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            {comic.ComicName}
          </Link>
          <span className="shrink-0 rounded-md border border-border-strong px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">
            {kindLabel}
          </span>
        </div>
        {mobileMeta ? (
          <div className="mt-0.5 truncate text-[11px] text-muted-foreground md:hidden">
            {mobileMeta}
          </div>
        ) : null}
      </div>

      <div className={`${DESKTOP_COL} text-foreground-2 truncate`}>
        {comic.ComicPublisher || "—"}
      </div>

      <div className={DESKTOP_COL}>
        <StatusBadge variant="dot" status={status || "unknown"} />
      </div>

      <div className={`${DESKTOP_COL} font-mono text-xs tabular-nums`}>
        <span>{have}</span>
        <span className="text-muted-foreground"> / {total}</span>
      </div>

      <div className={`${DESKTOP_COL} flex items-center gap-2`}>
        <div className="flex-1 h-1 bg-surface-3 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${progress}%`,
              background: "var(--status-downloaded)",
            }}
          />
        </div>
        <span className="mono-meta w-9 text-right tabular-nums">
          {total > 0 ? `${progress}%` : "–"}
        </span>
      </div>

      <div className={`mono-meta ${DESKTOP_COL} text-right`}>
        {comic.ComicYear || "—"}
      </div>
    </div>
  );
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
    <div className="w-[26px] h-[36px] bg-surface-2 rounded-[3px] overflow-hidden flex-shrink-0">
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
