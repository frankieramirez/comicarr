import { useState, useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  flexRender,
  ColumnDef,
  SortingState,
  RowSelectionState,
  CellContext,
  HeaderContext,
} from "@tanstack/react-table";
import {
  Download,
  X,
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
  Search,
  Filter,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import StatusBadge from "@/components/StatusBadge";
import EmptyState from "@/components/ui/EmptyState";
import { useQueueIssue, useUnqueueIssue } from "@/hooks/useSeries";
import { useBulkQueueIssues, useBulkUnqueueIssues } from "@/hooks/useQueue";
import { useToast } from "@/components/ui/toast";
import type { Issue } from "@/types";

type StatusFilter = "all" | "wanted" | "downloaded" | "skipped" | "other";

interface IssuesTableProps {
  issues?: Issue[];
}

export default function IssuesTable({ issues = [] }: IssuesTableProps) {
  const [sorting, setSorting] = useState<SortingState>([
    { id: "number", desc: false },
  ]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});

  const queueIssueMutation = useQueueIssue();
  const unqueueIssueMutation = useUnqueueIssue();
  const bulkQueueMutation = useBulkQueueIssues();
  const bulkUnqueueMutation = useBulkUnqueueIssues();
  const { addToast } = useToast();

  // Filter issues by status
  const filteredByStatus = useMemo(() => {
    if (statusFilter === "all") return issues;
    return issues.filter((issue) => {
      const status = (issue.status ?? issue.Status)?.toLowerCase();
      if (statusFilter === "other") {
        return !["wanted", "downloaded", "skipped", "snatched"].includes(
          status || ""
        );
      }
      return status === statusFilter;
    });
  }, [issues, statusFilter]);

  const handleQueueIssue = (e: React.MouseEvent, issueId: string) => {
    e.stopPropagation();
    queueIssueMutation.mutate(issueId);
  };

  const handleUnqueueIssue = (e: React.MouseEvent, issueId: string) => {
    e.stopPropagation();
    unqueueIssueMutation.mutate(issueId);
  };

  // Bulk actions
  const selectedIssueIds = useMemo(() => {
    return Object.keys(rowSelection)
      .map((index) => {
        const issue = filteredByStatus[parseInt(index)];
        return issue?.id ?? issue?.IssueID;
      })
      .filter(Boolean) as string[];
  }, [rowSelection, filteredByStatus]);

  const handleBulkWant = async () => {
    try {
      await bulkQueueMutation.mutateAsync(selectedIssueIds);
      addToast({
        type: "success",
        message: `${selectedIssueIds.length} issue${selectedIssueIds.length !== 1 ? "s" : ""} marked as wanted`,
      });
      setRowSelection({});
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to mark issues: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleBulkSkip = async () => {
    try {
      await bulkUnqueueMutation.mutateAsync(selectedIssueIds);
      addToast({
        type: "success",
        message: `${selectedIssueIds.length} issue${selectedIssueIds.length !== 1 ? "s" : ""} skipped`,
      });
      setRowSelection({});
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to skip issues: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleWantAll = async () => {
    const allIds = filteredByStatus
      .map((issue) => issue.id ?? issue.IssueID)
      .filter(Boolean) as string[];
    try {
      await bulkQueueMutation.mutateAsync(allIds);
      addToast({
        type: "success",
        message: `${allIds.length} issues marked as wanted`,
      });
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to mark issues: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const columns: ColumnDef<Issue>[] = [
    {
      id: "select",
      header: ({ table }: HeaderContext<Issue, unknown>) => (
        <Checkbox
          checked={table.getIsAllPageRowsSelected()}
          indeterminate={
            table.getIsSomePageRowsSelected() &&
            !table.getIsAllPageRowsSelected()
          }
          onChange={table.getToggleAllPageRowsSelectedHandler()}
        />
      ),
      cell: ({ row }: CellContext<Issue, unknown>) => (
        <Checkbox
          checked={row.getIsSelected()}
          onChange={row.getToggleSelectedHandler()}
        />
      ),
      size: 40,
      enableSorting: false,
    },
    {
      accessorKey: "number",
      header: "#",
      cell: ({ getValue }: CellContext<Issue, unknown>) => (
        <span className="font-mono text-sm">
          {(getValue() as string) || "N/A"}
        </span>
      ),
    },
    {
      accessorKey: "name",
      header: "Issue Name",
      cell: ({ row }: CellContext<Issue, unknown>) => (
        <div>
          <div className="font-medium">{row.original.number}</div>
          {row.original.name && (
            <div className="text-sm text-muted-foreground">
              {row.original.name}
            </div>
          )}
        </div>
      ),
    },
    {
      accessorKey: "releaseDate",
      header: "Release Date",
      cell: ({ getValue }: CellContext<Issue, unknown>) => {
        const date = getValue() as string | undefined;
        if (!date)
          return <span className="text-muted-foreground/70">N/A</span>;
        return <span className="text-sm">{date}</span>;
      },
    },
    {
      accessorKey: "status",
      header: "Status",
      cell: ({ row }: CellContext<Issue, unknown>) => (
        <StatusBadge status={row.original.status ?? row.original.Status} />
      ),
    },
    {
      id: "actions",
      header: "Actions",
      cell: ({ row }: CellContext<Issue, unknown>) => {
        const status = (
          row.original.status ?? row.original.Status
        )?.toLowerCase();
        const issueId = row.original.id ?? row.original.IssueID;

        return (
          <div className="flex items-center space-x-2">
            {status === "wanted" || status === "skipped" ? (
              <>
                {status === "wanted" && issueId && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => handleUnqueueIssue(e, issueId)}
                    disabled={unqueueIssueMutation.isPending}
                    className="text-xs"
                  >
                    <X className="w-3 h-3 mr-1" />
                    Skip
                  </Button>
                )}
                {status === "skipped" && issueId && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => handleQueueIssue(e, issueId)}
                    disabled={queueIssueMutation.isPending}
                    className="text-xs"
                  >
                    <Download className="w-3 h-3 mr-1" />
                    Want
                  </Button>
                )}
              </>
            ) : status !== "downloaded" && status !== "snatched" && issueId ? (
              <Button
                size="sm"
                variant="outline"
                onClick={(e) => handleQueueIssue(e, issueId)}
                disabled={queueIssueMutation.isPending}
                className="text-xs"
              >
                <Download className="w-3 h-3 mr-1" />
                Want
              </Button>
            ) : null}
          </div>
        );
      },
    },
  ];

  // Status counts for filter badges (must be before early return for hooks rules)
  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = { all: issues.length };
    issues.forEach((issue) => {
      const status = (issue.status ?? issue.Status)?.toLowerCase() || "other";
      counts[status] = (counts[status] || 0) + 1;
    });
    return counts;
  }, [issues]);

  const table = useReactTable({
    data: filteredByStatus,
    columns,
    state: {
      sorting,
      globalFilter,
      rowSelection,
    },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    enableRowSelection: true,
    initialState: {
      pagination: {
        pageSize: 50,
      },
    },
  });

  if (issues.length === 0) {
    return <EmptyState variant="issues" />;
  }

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
        {/* Search */}
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder="Search issues by number or name..."
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
            className="pl-9"
          />
        </div>

        {/* Status Filter & Quick Actions */}
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center gap-1 bg-muted rounded-lg p-1">
            <Filter className="w-4 h-4 ml-2 text-muted-foreground" />
            {(
              [
                ["all", "All"],
                ["wanted", "Wanted"],
                ["downloaded", "Downloaded"],
                ["skipped", "Skipped"],
              ] as const
            ).map(([value, label]) => (
              <Button
                key={value}
                variant={statusFilter === value ? "default" : "ghost"}
                size="sm"
                onClick={() => setStatusFilter(value)}
                className="h-7 text-xs"
              >
                {label}
                {statusCounts[value] !== undefined && (
                  <span className="ml-1 text-muted-foreground">
                    ({statusCounts[value]})
                  </span>
                )}
              </Button>
            ))}
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={handleWantAll}
            disabled={bulkQueueMutation.isPending || filteredByStatus.length === 0}
          >
            <Download className="w-3 h-3 mr-1" />
            Want All
          </Button>
        </div>
      </div>

      {/* Bulk Action Bar */}
      {selectedIssueIds.length > 0 && (
        <div className="flex items-center gap-4 px-4 py-3 bg-primary/10 border border-primary/20 rounded-lg">
          <span className="text-sm font-medium">
            {selectedIssueIds.length} issue
            {selectedIssueIds.length !== 1 ? "s" : ""} selected
          </span>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={handleBulkWant}
              disabled={bulkQueueMutation.isPending}
            >
              <Download className="w-3 h-3 mr-1" />
              Mark Wanted
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={handleBulkSkip}
              disabled={bulkUnqueueMutation.isPending}
            >
              <X className="w-3 h-3 mr-1" />
              Skip
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setRowSelection({})}
            >
              Clear
            </Button>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="rounded-lg border border-card-border bg-card card-shadow overflow-hidden">
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
                              header.getContext()
                            )}
                          </span>
                          {header.column.getCanSort() && (
                            <span className="text-muted-foreground">
                              {header.column.getIsSorted() === "asc" ? (
                                <ChevronUp className="w-4 h-4" />
                              ) : header.column.getIsSorted() === "desc" ? (
                                <ChevronDown className="w-4 h-4" />
                              ) : (
                                <ChevronsUpDown className="w-4 h-4 opacity-50" />
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
                  className={`hover:bg-accent/50 transition-colors ${
                    row.getIsSelected() ? "bg-primary/5" : ""
                  }`}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-6 py-4 whitespace-nowrap">
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext()
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="border-t border-card-border px-6 py-3 flex items-center justify-between bg-muted/50">
          <div className="text-sm text-muted-foreground">
            Showing{" "}
            {table.getState().pagination.pageIndex *
              table.getState().pagination.pageSize +
              1}{" "}
            to{" "}
            {Math.min(
              (table.getState().pagination.pageIndex + 1) *
                table.getState().pagination.pageSize,
              table.getFilteredRowModel().rows.length
            )}{" "}
            of {table.getFilteredRowModel().rows.length} issues
            {globalFilter && ` (filtered from ${filteredByStatus.length})`}
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
            <span className="text-sm text-muted-foreground">
              Page {table.getState().pagination.pageIndex + 1} of{" "}
              {table.getPageCount()}
            </span>
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
    </div>
  );
}
