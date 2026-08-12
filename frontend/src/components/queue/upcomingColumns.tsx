import { useMemo } from "react";
import { createColumnHelper } from "@tanstack/react-table";
import { CircleDot, Download, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import StatusBadge from "@/components/StatusBadge";
import { DataTableSortHeader } from "@/components/data-table/DataTableSortHeader";
import { CoverCell } from "@/components/data-table/cells/CoverCell";
import {
  type ComicarrTableFeatures,
  getIsAllSelected,
  toggleAllSelected,
} from "@/components/data-table/useTableState";
import { useQueueIssue, useUnqueueIssue } from "@/hooks/useSeries";
import type { UpcomingIssue } from "@/types";

const columnHelper = createColumnHelper<ComicarrTableFeatures, UpcomingIssue>();

/**
 * Columns for the Upcoming table. The table instance itself lives in
 * `ReleasesPage`'s `MyReleasesView`, which owns selection because it renders
 * `BulkActionBar` as a sibling; the columns live here so the page and the
 * selection tests drive the same select column (#395).
 */
export function useUpcomingColumns(onReview?: (issue: UpcomingIssue) => void) {
  const queueIssueMutation = useQueueIssue();
  const unqueueIssueMutation = useUnqueueIssue();

  return useMemo(
    () =>
      columnHelper.columns([
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
                {status === "wanted" && onReview ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(event) => {
                      event.stopPropagation();
                      onReview(row.original);
                    }}
                    className="text-xs"
                  >
                    <CircleDot className="mr-1 size-3" />
                    Review releases
                  </Button>
                ) : null}
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
      ]),
    [onReview, queueIssueMutation, unqueueIssueMutation],
  );
}
