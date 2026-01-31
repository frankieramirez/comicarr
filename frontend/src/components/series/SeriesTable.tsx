import { useState, useMemo, SyntheticEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  flexRender,
  ColumnDef,
  SortingState,
  CellContext,
} from "@tanstack/react-table";
import {
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
  BookOpen,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import StatusBadge from "@/components/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import EmptyState from "@/components/ui/EmptyState";
import SeriesFilters, {
  type TypeFilter,
  type ProgressFilter,
  type StatusFilter,
} from "./SeriesFilters";
import type { Comic } from "@/types";

interface SeriesTableProps {
  data?: Comic[];
  isLoading?: boolean;
}

// Helper to calculate progress percentage
function getProgressPercentage(comic: Comic): number {
  const total = parseInt(String(comic.Total)) || 0;
  const have = parseInt(String(comic.Have)) || 0;
  return total > 0 ? Math.round((have / total) * 100) : 0;
}

// Helper to get progress category
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

  // Get filters from URL params
  const typeFilter = (searchParams.get("type") as TypeFilter) || "all";
  const progressFilter =
    (searchParams.get("progress") as ProgressFilter) || "all";
  const statusFilter = (searchParams.get("status") as StatusFilter) || "all";

  // Update URL params when filters change
  const updateFilter = (key: string, value: string) => {
    const params = new URLSearchParams(searchParams);
    if (value === "all") {
      params.delete(key);
    } else {
      params.set(key, value);
    }
    setSearchParams(params, { replace: true });
  };

  // Calculate filter counts
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
      // Type counts
      const contentType = comic.ContentType?.toLowerCase();
      if (contentType === "manga") {
        counts.type.manga++;
      } else {
        counts.type.comic++;
      }

      // Progress counts
      const progressCategory = getProgressCategory(comic);
      counts.progress[progressCategory]++;

      // Status counts
      const status = comic.Status;
      if (status === "Active" || status === "Paused" || status === "Ended") {
        counts.status[status]++;
      }
    });

    return counts;
  }, [data]);

  // Filter data based on selected filters
  const filteredData = useMemo(() => {
    return data.filter((comic) => {
      // Type filter
      if (typeFilter !== "all") {
        const contentType = comic.ContentType?.toLowerCase();
        if (typeFilter === "manga" && contentType !== "manga") return false;
        if (typeFilter === "comic" && contentType === "manga") return false;
      }

      // Progress filter
      if (progressFilter !== "all") {
        const progressCategory = getProgressCategory(comic);
        if (progressCategory !== progressFilter) return false;
      }

      // Status filter
      if (statusFilter !== "all") {
        if (comic.Status !== statusFilter) return false;
      }

      return true;
    });
  }, [data, typeFilter, progressFilter, statusFilter]);

  const columns = useMemo<ColumnDef<Comic>[]>(
    () => [
      {
        accessorKey: "ComicName",
        header: "Series",
        cell: ({ row }: CellContext<Comic, unknown>) => (
          <div className="flex items-center space-x-3">
            {row.original.ComicImage && (
              <img
                src={row.original.ComicImage}
                alt={row.original.ComicName}
                className="w-10 h-14 object-cover rounded shadow-sm"
                onError={(e: SyntheticEvent<HTMLImageElement>) => {
                  e.currentTarget.style.display = "none";
                }}
              />
            )}
            <div>
              <div className="flex items-center gap-2">
                <span className="font-medium">{row.original.ComicName}</span>
                {row.original.ContentType?.toLowerCase() === "manga" ? (
                  <Badge variant="secondary" className="text-xs px-1.5 py-0">
                    <BookOpen className="w-3 h-3 mr-1" />
                    Manga
                  </Badge>
                ) : null}
              </div>
              {row.original.ComicYear && (
                <div className="text-sm text-gray-500">
                  ({row.original.ComicYear})
                </div>
              )}
            </div>
          </div>
        ),
      },
      {
        accessorKey: "ComicPublisher",
        header: "Publisher",
        cell: ({ getValue }: CellContext<Comic, unknown>) => (
          <span className="text-sm">{(getValue() as string) || "N/A"}</span>
        ),
      },
      {
        accessorKey: "Status",
        header: "Status",
        cell: ({ getValue }: CellContext<Comic, unknown>) => (
          <StatusBadge status={getValue() as string} />
        ),
      },
      {
        accessorKey: "Total",
        header: "Issues",
        cell: ({ row }: CellContext<Comic, unknown>) => (
          <div className="text-center">
            <span className="font-medium">{row.original.Have || 0}</span>
            <span className="text-gray-500"> / {row.original.Total || 0}</span>
          </div>
        ),
      },
      {
        id: "progress",
        header: "Progress",
        cell: ({ row }: CellContext<Comic, unknown>) => {
          const percentage = getProgressPercentage(row.original);

          return (
            <div className="flex items-center space-x-2">
              <div className="flex-1 bg-muted rounded-full h-2 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${percentage}%`,
                    background: "var(--gradient-brand)",
                  }}
                />
              </div>
              <span className="text-xs text-muted-foreground min-w-[3rem]">
                {percentage}%
              </span>
            </div>
          );
        },
      },
    ],
    [],
  );

  const table = useReactTable({
    data: filteredData,
    columns,
    state: {
      sorting,
      globalFilter,
    },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: {
      pagination: {
        pageSize: 20,
      },
    },
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
      {/* Filters & Search Row */}
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

        {/* Search */}
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

      {/* Table */}
      <div className="rounded-lg border-card-border bg-card card-shadow overflow-hidden">
        <div className="overflow-x-auto custom-scrollbar">
          <table className="w-full">
            <thead className="bg-muted/50 border-card-border backdrop-blur-sm border-b">
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <th
                      key={header.id}
                      className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider"
                    >
                      {header.isPlaceholder ? null : (
                        <div
                          className={
                            header.column.getCanSort()
                              ? "flex items-center space-x-1 cursor-pointer select-none hover:text-foreground"
                              : ""
                          }
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          <span>
                            {flexRender(
                              header.column.columnDef.header,
                              header.getContext(),
                            )}
                          </span>
                          {header.column.getCanSort() && (
                            <span className="text-gray-400">
                              {header.column.getIsSorted() === "asc" ? (
                                <ChevronUp className="w-4 h-4" />
                              ) : header.column.getIsSorted() === "desc" ? (
                                <ChevronDown className="w-4 h-4" />
                              ) : (
                                <ChevronsUpDown className="w-4 h-4" />
                              )}
                            </span>
                          )}
                        </div>
                      )}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody className="bg-card divide-y divide-card-border">
              {table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  onClick={() => navigate(`/series/${row.original.ComicID}`)}
                  className="hover:bg-accent/50 cursor-pointer transition-colors"
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-6 py-4 whitespace-nowrap">
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext(),
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between">
        <div className="text-sm text-gray-500">
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
