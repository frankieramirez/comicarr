import { useMemo } from "react";
import { createColumnHelper } from "@tanstack/react-table";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import StatusBadge from "@/components/StatusBadge";
import { DataTableSortHeader } from "@/components/data-table/DataTableSortHeader";
import { CoverCell } from "@/components/data-table/cells/CoverCell";
import {
  getIsAllSelected,
  toggleAllSelected,
} from "@/components/data-table/useTableState";
import { useUnqueueIssue } from "@/hooks/useSeries";
import type { WantedIssue } from "@/types";

const columnHelper = createColumnHelper<WantedIssue>();

/**
 * Columns for the Wanted table. The table instance itself lives in
 * `WantedPage`, which owns selection because it renders `BulkActionBar` as a
 * sibling; the columns live here so the page and the selection tests drive the
 * same select column (#395).
 */
export function useWantedColumns() {
  const unqueueIssueMutation = useUnqueueIssue();

  return useMemo(
    () => [
      columnHelper.display({
        id: "select",
        header: ({ table }) => (
          <Checkbox
            checked={getIsAllSelected(table)}
            onCheckedChange={(value) => toggleAllSelected(table, !!value)}
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
}
