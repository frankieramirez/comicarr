import { useState, useMemo, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  createColumnHelper,
  type SortingState,
  type RowSelectionState,
} from "@tanstack/react-table";
import { Trash2, Pause, Play, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import StatusBadge from "@/components/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import EmptyState from "@/components/ui/EmptyState";
import { DataTable } from "@/components/data-table/DataTable";
import { DataTableSortHeader } from "@/components/data-table/DataTableSortHeader";
import { CoverCell } from "@/components/data-table/cells/CoverCell";
import { ProgressBarCell } from "@/components/data-table/cells/ProgressBarCell";
import { IssueCountCell } from "@/components/data-table/cells/IssueCountCell";
import SeriesFilters, {
  type TypeFilter,
  type ProgressFilter,
  type StatusFilter,
} from "./SeriesFilters";
import { useDebounce } from "@/hooks/use-debounce";
import {
  useBulkDeleteSeries,
  useBulkPauseSeries,
  useBulkResumeSeries,
} from "@/hooks/useSeries";
import { useToast } from "@/components/ui/toast";
import type { Comic } from "@/types";

const columnHelper = createColumnHelper<Comic>();

interface SeriesTableProps {
  data?: Comic[];
  isLoading?: boolean;
}

function getProgressPercentage(comic: Comic): number {
  const total = parseInt(String(comic.Total)) || 0;
  const have = parseInt(String(comic.Have)) || 0;
  return total > 0 ? Math.round((have / total) * 100) : 0;
}

function getProgressCategory(comic: Comic): "0" | "partial" | "100" {
  const percentage = getProgressPercentage(comic);
  if (percentage === 0) return "0";
  if (percentage === 100) return "100";
  return "partial";
}

export default function SeriesTable({
  data = [],
  isLoading,
}: SeriesTableProps) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [confirmDelete, setConfirmDelete] = useState(false);
  const debouncedFilter = useDebounce(globalFilter, 300);

  const bulkDeleteMutation = useBulkDeleteSeries();
  const bulkPauseMutation = useBulkPauseSeries();
  const bulkResumeMutation = useBulkResumeSeries();
  const { addToast } = useToast();

  const typeFilter = (searchParams.get("type") as TypeFilter) || "all";
  const progressFilter =
    (searchParams.get("progress") as ProgressFilter) || "all";
  const statusFilter = (searchParams.get("status") as StatusFilter) || "all";

  const updateFilter = useCallback(
    (key: string, value: string) => {
      const params = new URLSearchParams(searchParams);
      if (value === "all") {
        params.delete(key);
      } else {
        params.set(key, value);
      }
      setSearchParams(params, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const filterCounts = useMemo(() => {
    const counts = {
      type: { all: data.length, comic: 0, manga: 0 } as Record<
        TypeFilter,
        number
      >,
      progress: { all: data.length, "0": 0, partial: 0, "100": 0 } as Record<
        ProgressFilter,
        number
      >,
      status: { all: data.length, Active: 0, Paused: 0, Ended: 0 } as Record<
        StatusFilter,
        number
      >,
    };

    data.forEach((comic) => {
      const contentType = comic.ContentType?.toLowerCase();
      if (contentType === "manga") counts.type.manga++;
      else counts.type.comic++;

      counts.progress[getProgressCategory(comic)]++;

      const status = comic.Status;
      if (status === "Active" || status === "Paused" || status === "Ended") {
        counts.status[status]++;
      }
    });

    return counts;
  }, [data]);

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

  const columns = useMemo(
    () => [
      columnHelper.display({
        id: "select",
        header: ({ table }) => (
          <Checkbox
            checked={
              table.getIsAllPageRowsSelected() ||
              (table.getIsSomePageRowsSelected() && "indeterminate")
            }
            onCheckedChange={(value) =>
              table.toggleAllPageRowsSelected(!!value)
            }
          />
        ),
        cell: ({ row }) => (
          <div onClick={(e) => e.stopPropagation()}>
            <Checkbox
              checked={row.getIsSelected()}
              onCheckedChange={(value) => row.toggleSelected(!!value)}
            />
          </div>
        ),
        size: 40,
        enableSorting: false,
      }),
      columnHelper.accessor("ComicName", {
        header: ({ column }) => (
          <DataTableSortHeader column={column} title="Series" />
        ),
        cell: ({ row }) => (
          <CoverCell
            variant="full"
            imageUrl={row.original.ComicImage}
            title={row.original.ComicName}
            year={row.original.ComicYear}
            isManga={row.original.ContentType?.toLowerCase() === "manga"}
          />
        ),
      }),
      columnHelper.accessor("ComicPublisher", {
        header: ({ column }) => (
          <DataTableSortHeader column={column} title="Publisher" />
        ),
        cell: ({ getValue }) => (
          <span className="text-sm">{getValue() || "N/A"}</span>
        ),
      }),
      columnHelper.accessor("Status", {
        header: ({ column }) => (
          <DataTableSortHeader column={column} title="Status" />
        ),
        cell: ({ getValue }) => <StatusBadge status={getValue()} />,
      }),
      columnHelper.accessor("Total", {
        header: "Issues",
        cell: ({ row }) => (
          <IssueCountCell
            have={parseInt(String(row.original.Have)) || 0}
            total={parseInt(String(row.original.Total)) || 0}
          />
        ),
        enableSorting: false,
      }),
      columnHelper.display({
        id: "progress",
        header: "Progress",
        cell: ({ row }) => (
          <ProgressBarCell percentage={getProgressPercentage(row.original)} />
        ),
        enableSorting: false,
      }),
    ],
    [],
  );

  const table = useReactTable({
    data: filteredData,
    columns,
    state: { sorting, globalFilter: debouncedFilter, rowSelection },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
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
    initialState: { pagination: { pageSize: 20 } },
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-full max-w-sm" />
        {[...Array(10)].map((_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    );
  }

  if (data.length === 0) {
    return <EmptyState variant="library" />;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 justify-between">
        <SeriesFilters
          typeFilter={typeFilter}
          progressFilter={progressFilter}
          statusFilter={statusFilter}
          onTypeChange={(value) => updateFilter("type", value)}
          onProgressChange={(value) => updateFilter("progress", value)}
          onStatusChange={(value) => updateFilter("status", value)}
          counts={filterCounts}
        />
        <div className="flex items-center gap-2">
          <Input
            placeholder="Search series..."
            value={globalFilter ?? ""}
            onChange={(e) => setGlobalFilter(e.target.value)}
            className="w-[200px]"
          />
          <span className="text-sm text-muted-foreground whitespace-nowrap">
            {table.getFilteredRowModel().rows.length} series
          </span>
        </div>
      </div>

      {/* Bulk Action Bar */}
      {selectedSeriesIds.length > 0 && (
        <div className="flex items-center gap-4 px-4 py-3 bg-primary/10 border border-primary/20 rounded-lg">
          <span className="text-sm font-medium">
            {selectedSeriesIds.length} series selected
          </span>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="destructive"
              onClick={handleBulkDelete}
              disabled={bulkDeleteMutation.isPending}
            >
              <Trash2 className="w-3 h-3 mr-1" />
              {confirmDelete ? "Confirm Delete" : "Delete"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={handleBulkPause}
              disabled={bulkPauseMutation.isPending}
            >
              <Pause className="w-3 h-3 mr-1" />
              Pause
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={handleBulkResume}
              disabled={bulkResumeMutation.isPending}
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
            >
              <X className="w-3 h-3 mr-1" />
              Clear
            </Button>
          </div>
        </div>
      )}

      <DataTable
        table={table}
        onRowClick={(row) => navigate(`/series/${row.ComicID}`)}
      />

      <div className="flex items-center justify-between">
        <div className="text-sm text-muted-foreground">
          Page {table.getState().pagination.pageIndex + 1} of{" "}
          {table.getPageCount()}
        </div>
        <div className="flex items-center space-x-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
