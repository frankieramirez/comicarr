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
import { useToast } from "@/components/ui/toast";
import { useQueueIssue, useUnqueueIssue } from "@/hooks/useSeries";
import { getErrorMessage } from "@/lib/api";
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
  const { addToast } = useToast();

  return useMemo(() => {
    const reportMutationError = (err: unknown) => {
      addToast({ type: "error", message: getErrorMessage(err) });
    };
    return columnHelper.columns([
      columnHelper.display({
        id: "select",
        header: ({ table }) => (
          <Checkbox
            aria-label="Select all rows"
            checked={getIsAllSelected(table)}
            onCheckedChange={(value) => toggleAllSelected(table, !!value)}
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            aria-label={`Select ${row.original.ComicName}`}
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
        cell: ({ row }) => (
          <div className="[&>div]:h-9 [&>div]:w-[26px] [&>div]:rounded-[3px]">
            <CoverCell comicId={row.original.ComicID} />
          </div>
        ),
        size: 44,
        enableSorting: false,
      }),
      columnHelper.accessor("ComicName", {
        header: ({ column }) => (
          <DataTableSortHeader column={column} title="Series" />
        ),
        cell: ({ row }) => (
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="truncate text-sm font-medium text-foreground">
              {row.original.ComicName}
            </span>
            {row.original.ComicYear && (
              <span className="mono-meta shrink-0">
                {row.original.ComicYear}
              </span>
            )}
          </div>
        ),
      }),
      columnHelper.accessor("IssueNumber", {
        header: "#",
        cell: ({ getValue }) => (
          <span className="font-mono text-[13px] text-foreground-2">
            {getValue() || "N/A"}
          </span>
        ),
        enableSorting: false,
      }),
      columnHelper.accessor("IssueName", {
        header: "Issue",
        cell: ({ getValue }) => {
          const name = getValue();
          return name ? (
            <span className="text-sm text-foreground-2">{name}</span>
          ) : (
            <span className="text-sm text-muted-foreground">N/A</span>
          );
        },
        enableSorting: false,
      }),
      columnHelper.accessor("IssueDate", {
        header: ({ column }) => (
          <DataTableSortHeader column={column} title="Released" />
        ),
        cell: ({ getValue }) => {
          const date = getValue();
          if (!date) return <span className="text-muted-foreground">N/A</span>;
          return (
            <span className="font-mono text-xs text-foreground-2">{date}</span>
          );
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
        header: () => <span className="sr-only">Actions</span>,
        cell: ({ row }) => {
          const status = row.original.Status?.toLowerCase();
          const issueId = row.original.IssueID;

          return (
            <div className="flex items-center justify-end gap-1 opacity-70 transition-opacity group-hover/row:opacity-100 focus-within:opacity-100">
              {status === "wanted" && onReview ? (
                <Button
                  size="compact"
                  variant="ghost"
                  onClick={(event) => {
                    event.stopPropagation();
                    onReview(row.original);
                  }}
                  className="text-foreground-2"
                >
                  <CircleDot />
                  Review releases
                </Button>
              ) : null}
              {status === "wanted" || status === "skipped" ? (
                <>
                  {status === "wanted" && (
                    <Button
                      size="compact"
                      variant="ghost"
                      onClick={(e) => {
                        e.stopPropagation();
                        unqueueIssueMutation.mutate(issueId, {
                          onSuccess: () =>
                            addToast({
                              type: "success",
                              message: "1 issue skipped",
                            }),
                          onError: reportMutationError,
                        });
                      }}
                      disabled={unqueueIssueMutation.isPending}
                      className="text-foreground-2"
                    >
                      <X />
                      Skip
                    </Button>
                  )}
                  {status === "skipped" && (
                    <Button
                      size="compact"
                      variant="ghost"
                      onClick={(e) => {
                        e.stopPropagation();
                        queueIssueMutation.mutate(issueId, {
                          onSuccess: () =>
                            addToast({
                              type: "success",
                              message: "1 issue queued",
                            }),
                          onError: reportMutationError,
                        });
                      }}
                      disabled={queueIssueMutation.isPending}
                      className="text-foreground-2"
                    >
                      <Download />
                      Want
                    </Button>
                  )}
                </>
              ) : status !== "downloaded" && status !== "snatched" ? (
                <Button
                  size="compact"
                  variant="ghost"
                  onClick={(e) => {
                    e.stopPropagation();
                    queueIssueMutation.mutate(issueId, {
                      onSuccess: () =>
                        addToast({
                          type: "success",
                          message: "1 issue queued",
                        }),
                      onError: reportMutationError,
                    });
                  }}
                  disabled={queueIssueMutation.isPending}
                  className="text-foreground-2"
                >
                  <Download />
                  Want
                </Button>
              ) : null}
            </div>
          );
        },
      }),
    ]);
  }, [addToast, onReview, queueIssueMutation, unqueueIssueMutation]);
}
