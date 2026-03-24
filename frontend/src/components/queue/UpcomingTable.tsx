import { useState, useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  createColumnHelper,
  type SortingState,
  type RowSelectionState,
  type Updater,
} from "@tanstack/react-table";
import { Download, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import StatusBadge from "@/components/StatusBadge";
import { DataTable } from "@/components/data-table/DataTable";
import { DataTableSortHeader } from "@/components/data-table/DataTableSortHeader";
import { CoverCell } from "@/components/data-table/cells/CoverCell";
import { useQueueIssue, useUnqueueIssue } from "@/hooks/useSeries";
import type { UpcomingIssue } from "@/types";

const columnHelper = createColumnHelper<UpcomingIssue>();

interface UpcomingTableProps {
  issues?: UpcomingIssue[];
  onSelectionChange?: (selectedIds: string[]) => void;
}

export default function UpcomingTable({
  issues = [],
  onSelectionChange,
}: UpcomingTableProps) {
  const [sorting, setSorting] = useState<SortingState>([
    { id: "IssueDate", desc: false },
  ]);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const queueIssueMutation = useQueueIssue();
  const unqueueIssueMutation = useUnqueueIssue();

  const columns = useMemo(
    () => [
      columnHelper.display({
        id: "select",
        header: ({ table }) => (
          <Checkbox
            checked={
              table.getIsAllRowsSelected() ||
              (table.getIsSomeRowsSelected() && "indeterminate")
            }
            onCheckedChange={(value) => table.toggleAllRowsSelected(!!value)}
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            checked={row.getIsSelected()}
            onCheckedChange={(value) => row.toggleSelected(!!value)}
            onClick={(e) => e.stopPropagation()}
          />
        ),
        size: 40,
      }),
      columnHelper.display({
        id: "cover",
        header: "",
        cell: ({ row }) => <CoverCell comicId={row.original.ComicID} />,
        size: 60,
        enableSorting: false,
      }),
      columnHelper.accessor("ComicName", {
        header: ({ column }) => (
          <DataTableSortHeader column={column} title="Series" />
        ),
        cell: ({ row }) => (
          <div>
            <div className="font-medium">{row.original.ComicName}</div>
            {row.original.ComicYear && (
              <div className="text-sm text-muted-foreground">
                ({row.original.ComicYear})
              </div>
            )}
          </div>
        ),
      }),
      columnHelper.accessor("IssueNumber", {
        header: "#",
        cell: ({ getValue }) => (
          <span className="font-mono text-sm">{getValue() || "N/A"}</span>
        ),
        enableSorting: false,
      }),
      columnHelper.accessor("IssueName", {
        header: "Issue Name",
        cell: ({ getValue }) => {
          const name = getValue();
          return name ? (
            <span className="text-sm text-foreground">{name}</span>
          ) : (
            <span className="text-sm text-muted-foreground/70">N/A</span>
          );
        },
        enableSorting: false,
      }),
      columnHelper.accessor("IssueDate", {
        header: ({ column }) => (
          <DataTableSortHeader column={column} title="Release Date" />
        ),
        cell: ({ getValue }) => {
          const date = getValue();
          if (!date)
            return <span className="text-muted-foreground/70">N/A</span>;
          return <span className="text-sm">{date}</span>;
        },
      }),
      columnHelper.accessor((row) => row.Status ?? "", {
        id: "Status",
        header: "Status",
        cell: ({ getValue }) => <StatusBadge status={getValue()} />,
        enableSorting: false,
      }),
      columnHelper.display({
        id: "actions",
        header: "Actions",
        cell: ({ row }) => {
          const status = row.original.Status?.toLowerCase();
          const issueId = row.original.IssueID;

          return (
            <div className="flex items-center space-x-2">
              {status === "wanted" || status === "skipped" ? (
                <>
                  {status === "wanted" && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={(e) => {
                        e.stopPropagation();
                        unqueueIssueMutation.mutate(issueId);
                      }}
                      disabled={unqueueIssueMutation.isPending}
                      className="text-xs"
                    >
                      <X className="w-3 h-3 mr-1" />
                      Skip
                    </Button>
                  )}
                  {status === "skipped" && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={(e) => {
                        e.stopPropagation();
                        queueIssueMutation.mutate(issueId);
                      }}
                      disabled={queueIssueMutation.isPending}
                      className="text-xs"
                    >
                      <Download className="w-3 h-3 mr-1" />
                      Want
                    </Button>
                  )}
                </>
              ) : status !== "downloaded" && status !== "snatched" ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={(e) => {
                    e.stopPropagation();
                    queueIssueMutation.mutate(issueId);
                  }}
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
      }),
    ],
    [queueIssueMutation, unqueueIssueMutation],
  );

  const table = useReactTable({
    data: issues,
    columns,
    state: { sorting, rowSelection },
    onSortingChange: setSorting,
    onRowSelectionChange: (updater: Updater<RowSelectionState>) => {
      setRowSelection(updater);
      if (onSelectionChange) {
        const newSelection =
          typeof updater === "function" ? updater(rowSelection) : updater;
        const selectedIds = Object.keys(newSelection)
          .map((index) => issues[parseInt(index)]?.IssueID)
          .filter(Boolean) as string[];
        onSelectionChange(selectedIds);
      }
    },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (row) => row.IssueID,
    enableRowSelection: true,
  });

  if (issues.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        No upcoming releases this week.
      </div>
    );
  }

  return <DataTable table={table} />;
}
