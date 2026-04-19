import { useState, useMemo, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  createColumnHelper,
  type SortingState,
  type RowSelectionState,
  type Row,
} from "@tanstack/react-table";
import {
  useQueryState,
  useQueryStates,
  parseAsInteger,
  parseAsString,
  parseAsStringLiteral,
  createParser,
} from "nuqs";
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
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import EmptyState from "@/components/ui/EmptyState";
import SeriesFilters, {
  type TypeFilter,
  type ProgressFilter,
  type StatusFilter,
} from "./SeriesFilters";
import SeriesGrid from "./SeriesGrid";
import { SORT_DELIMITER } from "@/lib/delimiters";
import { getProgressPercentage, getProgressCategory } from "@/lib/series-utils";
import {
  useBulkDeleteSeries,
  useBulkPauseSeries,
  useBulkResumeSeries,
} from "@/hooks/useSeries";
import { useToast } from "@/components/ui/toast";
import type { Comic } from "@/types";

const columnHelper = createColumnHelper<Comic>();

const sortParser = createParser({
  parse(value: string) {
    const [id, direction] = value.split(SORT_DELIMITER);
    if (!id) return null;
    return { id, desc: direction === "desc" };
  },
  serialize(value: { id: string; desc: boolean }) {
    return `${value.id}${SORT_DELIMITER}${value.desc ? "desc" : "asc"}`;
  },
});

const seriesParams = {
  page: parseAsInteger.withDefault(0),
  sort: sortParser,
  type: parseAsStringLiteral(["comic", "manga"] as const),
  progress: parseAsStringLiteral(["0", "partial", "100"] as const),
  status: parseAsStringLiteral(["Active", "Paused", "Ended"] as const),
  view: parseAsStringLiteral(["list", "grid"] as const).withDefault("list"),
};

// Grid layout: [checkbox, cover, title, publisher, status, issues, progress, year]
const GRID_COLS = "20px 40px minmax(0,1fr) 160px 100px 110px 180px 60px";

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
  const [search, setSearch] = useQueryState(
    "search",
    parseAsString.withDefault("").withOptions({
      history: "replace",
      throttleMs: 300,
    }),
  );
  const [searchInput, setSearchInput] = useState(search);
  const [localPage, setLocalPage] = useState(params.page);

  useEffect(() => {
    setSearchInput(search);
  }, [search]);

  useEffect(() => {
    setLocalPage(params.page);
  }, [params.page]);

  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [confirmDelete, setConfirmDelete] = useState(false);

  const bulkDeleteMutation = useBulkDeleteSeries();
  const bulkPauseMutation = useBulkPauseSeries();
  const bulkResumeMutation = useBulkResumeSeries();
  const { addToast } = useToast();

  const typeFilter: TypeFilter = params.type ?? "all";
  const progressFilter: ProgressFilter = params.progress ?? "all";
  const statusFilter: StatusFilter = params.status ?? "all";

  const sorting: SortingState = params.sort ? [params.sort] : [];
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

  const maxPageEstimate = Math.max(
    0,
    Math.ceil(filteredData.length / pageSize) - 1,
  );
  const effectivePage = Math.min(Math.max(localPage, 0), maxPageEstimate);

  const pagination = useMemo(
    () => ({ pageIndex: effectivePage, pageSize }),
    [effectivePage, pageSize],
  );

  const selectedSeriesIds = useMemo(() => {
    return Object.keys(rowSelection).filter((id) => rowSelection[id]);
  }, [rowSelection]);

  const handleBulkDelete = async () => {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    try {
      await bulkDeleteMutation.mutateAsync(selectedSeriesIds);
      addToast({
        type: "success",
        message: `${selectedSeriesIds.length} series deleted`,
      });
      setRowSelection({});
      setConfirmDelete(false);
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
      setRowSelection({});
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
      setRowSelection({});
    } catch {
      addToast({
        type: "error",
        title: "Error",
        description: "Failed to resume series",
      });
    }
  };

  // Columns are only used by TanStack for sorting & filtering state; rendering
  // is done inline below to match the compact grid design.
  const columns = useMemo(
    () => [
      columnHelper.accessor("ComicName", { id: "ComicName" }),
      columnHelper.accessor("ComicPublisher", { id: "ComicPublisher" }),
      columnHelper.accessor("Status", { id: "Status" }),
      columnHelper.accessor("ComicYear", { id: "ComicYear" }),
    ],
    [],
  );

  const table = useReactTable({
    data: filteredData,
    columns,
    state: { sorting, globalFilter: searchInput, rowSelection, pagination },
    onSortingChange: (updaterOrValue) => {
      const newSorting =
        typeof updaterOrValue === "function"
          ? updaterOrValue(sorting)
          : updaterOrValue;
      setLocalPage(0);
      setParams({
        sort: newSorting.length > 0 ? newSorting[0] : null,
        page: null,
      });
    },
    onPaginationChange: (updaterOrValue) => {
      const newPagination =
        typeof updaterOrValue === "function"
          ? updaterOrValue(pagination)
          : updaterOrValue;
      const newPage = newPagination.pageIndex;
      if (newPage !== effectivePage) {
        setLocalPage(newPage);
        setParams({ page: newPage === 0 ? null : newPage });
      }
    },
    onRowSelectionChange: (updater) => {
      setConfirmDelete(false);
      setRowSelection(updater);
    },
    getRowId: (row) => row.ComicID,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    enableRowSelection: true,
  });

  const pageCount = table.getPageCount();

  useEffect(() => {
    const maxPage = Math.max(0, pageCount - 1);
    const clampedPage = Math.min(Math.max(localPage, 0), maxPage);

    if (clampedPage !== localPage) {
      setLocalPage(clampedPage);
      setParams({ page: clampedPage === 0 ? null : clampedPage });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageCount, localPage]);

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
    setLocalPage(0);
    setParams({ sort: next[0] ?? null, page: null });
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
      {/* Filter bar */}
      <div className="px-5 py-2.5 border-b border-border flex items-center gap-3 min-h-[44px]">
        <SeriesFilters
          typeFilter={typeFilter}
          progressFilter={progressFilter}
          statusFilter={statusFilter}
          onTypeChange={(value) => {
            setLocalPage(0);
            setParams({ type: value === "all" ? null : value, page: null });
          }}
          onProgressChange={(value) => {
            setLocalPage(0);
            setParams({ progress: value === "all" ? null : value, page: null });
          }}
          onStatusChange={(value) => {
            setLocalPage(0);
            setParams({ status: value === "all" ? null : value, page: null });
          }}
          resultCount={totalFiltered}
          sortLabel={sortLabel}
        />
      </div>

      {/* View toggle + search */}
      <div className="px-5 py-2 border-b border-border flex items-center gap-2">
        <div className="inline-flex rounded-md border border-border overflow-hidden">
          <button
            type="button"
            onClick={() => {
              setParams({ view: null });
              setRowSelection({});
            }}
            className={`px-2 py-1 transition-colors ${
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
              setLocalPage(0);
              setParams({ view: "grid", page: null });
              setRowSelection({});
            }}
            className={`px-2 py-1 border-l border-border transition-colors ${
              isGridView
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
            aria-label="Grid view"
          >
            <LayoutGrid className="w-3.5 h-3.5" />
          </button>
        </div>
        <Input
          placeholder="Search series…"
          value={searchInput}
          onChange={(e) => {
            setSearchInput(e.target.value);
            setSearch(e.target.value || null);
            setLocalPage(0);
            setParams({ page: null });
          }}
          className="w-[220px] h-8 text-[12px]"
        />
      </div>

      {/* Bulk action bar */}
      {!isGridView && selectedSeriesIds.length > 0 && (
        <div className="px-5 py-2 border-b border-border flex items-center gap-3 bg-primary/5">
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
              setRowSelection({});
              setConfirmDelete(false);
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
        <>
          <div
            className="px-5 py-2 grid items-center gap-3 border-b border-border bg-muted/30 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70"
            style={{ gridTemplateColumns: GRID_COLS }}
          >
            <Checkbox
              checked={
                table.getIsAllPageRowsSelected() ||
                (table.getIsSomePageRowsSelected() && "indeterminate")
              }
              onCheckedChange={(value) =>
                table.toggleAllPageRowsSelected(!!value)
              }
            />
            <span />
            <SortHeader
              label="title"
              active={sorting[0]?.id === "ComicName"}
              desc={sorting[0]?.id === "ComicName" && sorting[0].desc}
              onClick={() => toggleSort("ComicName")}
            />
            <SortHeader
              label="publisher"
              active={sorting[0]?.id === "ComicPublisher"}
              desc={sorting[0]?.id === "ComicPublisher" && sorting[0].desc}
              onClick={() => toggleSort("ComicPublisher")}
            />
            <SortHeader
              label="status"
              active={sorting[0]?.id === "Status"}
              desc={sorting[0]?.id === "Status" && sorting[0].desc}
              onClick={() => toggleSort("Status")}
            />
            <span>issues</span>
            <span>progress</span>
            <span className="text-right">
              <SortHeader
                label="yr"
                active={sorting[0]?.id === "ComicYear"}
                desc={sorting[0]?.id === "ComicYear" && sorting[0].desc}
                onClick={() => toggleSort("ComicYear")}
                align="right"
              />
            </span>
          </div>

          <div className="flex-1 min-h-0 overflow-auto">
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

          {/* Footer */}
          <div className="px-5 py-1.5 border-t border-border bg-muted/30 flex items-center gap-3 font-mono text-[10px] text-muted-foreground">
            <span>
              {pageRows.length} of {totalFiltered} shown
            </span>
            {selectedSeriesIds.length > 0 && (
              <>
                <span className="text-muted-foreground/50">·</span>
                <span>{selectedSeriesIds.length} selected</span>
              </>
            )}
            {pageCount > 1 && (
              <>
                <span className="text-muted-foreground/50">·</span>
                <span>
                  page {effectivePage + 1} of {pageCount}
                </span>
                <button
                  type="button"
                  onClick={() => table.previousPage()}
                  disabled={!table.getCanPreviousPage()}
                  className="px-1 hover:text-foreground disabled:opacity-40"
                >
                  prev
                </button>
                <button
                  type="button"
                  onClick={() => table.nextPage()}
                  disabled={!table.getCanNextPage()}
                  className="px-1 hover:text-foreground disabled:opacity-40"
                >
                  next
                </button>
              </>
            )}
          </div>
        </>
      )}
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
  row: Row<Comic>;
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

  return (
    <div
      onClick={onClick}
      className={`px-5 py-2 grid items-center gap-3 border-b border-border/50 text-[12.5px] cursor-pointer transition-colors ${
        isSelected ? "bg-primary/10" : "hover:bg-muted/40"
      }`}
      style={{ gridTemplateColumns: GRID_COLS }}
    >
      <div onClick={(e) => e.stopPropagation()}>
        <Checkbox
          checked={isSelected}
          onCheckedChange={(value) => row.toggleSelected(!!value)}
        />
      </div>

      <CoverThumb url={comic.ComicImage} alt={comic.ComicName} />

      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium truncate">{comic.ComicName}</span>
          <span className="font-mono text-[9px] text-muted-foreground/70 px-1 py-[1px] border border-border rounded-[3px] uppercase tracking-wider flex-shrink-0">
            {kindLabel}
          </span>
        </div>
        {comic.ComicYear && (
          <div className="text-[11px] text-muted-foreground mt-0.5">
            ({comic.ComicYear})
          </div>
        )}
      </div>

      <div className="text-muted-foreground truncate">
        {comic.ComicPublisher || "—"}
      </div>

      <div
        className="inline-flex items-center gap-1.5 font-mono text-[10px]"
        style={{ color: statusColor }}
      >
        <span
          className="inline-block w-1.5 h-1.5 rounded-full"
          style={{ background: statusColor }}
        />
        {status || "unknown"}
      </div>

      <div className="font-mono text-[12px] tabular-nums">
        <span>{have}</span>
        <span className="text-muted-foreground/60">/{total}</span>
      </div>

      <div className="flex items-center gap-2">
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

      <div className="font-mono text-[11px] text-muted-foreground/70 text-right">
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
  url?: string | null;
  alt?: string;
}

function CoverThumb({ url, alt }: CoverThumbProps) {
  const [erroredUrl, setErroredUrl] = useState<string | null>(null);
  const errored = erroredUrl !== null && erroredUrl === url;

  return (
    <div className="w-[32px] h-[44px] bg-muted rounded-sm overflow-hidden flex-shrink-0">
      {url && !errored ? (
        <img
          src={url}
          alt={alt || ""}
          className="w-full h-full object-cover"
          loading="lazy"
          onError={() => setErroredUrl(url)}
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-muted-foreground/40">
          <ImageOff className="w-3 h-3" />
        </div>
      )}
    </div>
  );
}
