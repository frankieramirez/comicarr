import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  createColumnHelper,
  type SortingState,
  type RowSelectionState,
  type Updater,
} from "@tanstack/react-table";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import StatusBadge from "@/components/StatusBadge";
import EmptyState from "@/components/ui/EmptyState";
import { DataTable } from "@/components/data-table/DataTable";
import { DataTableSortHeader } from "@/components/data-table/DataTableSortHeader";
import { DataTableServerPagination } from "@/components/data-table/DataTableServerPagination";
import { CoverCell } from "@/components/data-table/cells/CoverCell";
import { useUnqueueIssue } from "@/hooks/useSeries";
import type { WantedIssue, PaginationMeta } from "@/types";

const columnHelper = createColumnHelper<WantedIssue>();

interface WantedTableProps {
  issues?: WantedIssue[];
  pagination?: PaginationMeta;
  onNextPage?: () => void;
  onPrevPage?: () => void;
  onSelectionChange?: (selectedIds: string[]) => void;
}

export default function WantedTable({
  issues = [],
  pagination,
  onNextPage,
  onPrevPage,
  onSelectionChange,
}: WantedTableProps) {
  const navigate = useNavigate();
  const [sorting, setSorting] = useState<SortingState>([
    { id: "DateAdded", desc: true },
  ]);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
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
      columnHelper.accessor("Issue_Number", {
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
      columnHelper.accessor("DateAdded", {
        header: ({ column }) => (
          <DataTableSortHeader column={column} title="Date Added" />
        ),
        cell: ({ getValue }) => {
          const date = getValue();
          if (!date)
            return <span className="text-muted-foreground/70">N/A</span>;
          return <span className="text-sm">{date}</span>;
        },
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
      columnHelper.accessor("Status", {
        header: "Status",
        cell: ({ getValue }) => <StatusBadge status={getValue()} />,
        enableSorting: false,
      }),
      columnHelper.display({
        id: "actions",
        header: "Actions",
        cell: ({ row }) => (
          <Button
            size="sm"
            variant="outline"
            onClick={(e) => {
              e.stopPropagation();
              unqueueIssueMutation.mutate(row.original.IssueID);
            }}
            disabled={unqueueIssueMutation.isPending}
            className="text-xs"
          >
            <X className="w-3 h-3 mr-1" />
            Skip
          </Button>
        ),
      }),
    ],
    [unqueueIssueMutation],
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
    return <EmptyState variant="wanted" />;
  }

  return (
    <div>
      <DataTable
        table={table}
        onRowClick={(row) => navigate(`/series/${row.ComicID}`)}
      />
      {pagination && onNextPage && onPrevPage && (
        <DataTableServerPagination
          pagination={pagination}
          onNextPage={onNextPage}
          onPrevPage={onPrevPage}
        />
      )}
    </div>
  );
}
