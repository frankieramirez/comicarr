import { useMemo } from "react";
import { Link } from "react-router-dom";
import { createColumnHelper } from "@tanstack/react-table";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { DataTableSortHeader } from "@/components/data-table/DataTableSortHeader";
import { CoverCell } from "@/components/data-table/cells/CoverCell";
import {
  type ComicarrTableFeatures,
  getIsAllSelected,
  toggleAllSelected,
} from "@/components/data-table/useTableState";
import { useToast } from "@/components/ui/toast";
import { useUnqueueIssue } from "@/hooks/useSeries";
import { getErrorMessage } from "@/lib/api";
import { formatWantedAcquisitionAnnotation } from "@/lib/wantedAnnotation";
import type { WantedIssue } from "@/types";

const columnHelper = createColumnHelper<ComicarrTableFeatures, WantedIssue>();

/**
 * Columns for the Wanted table. The table instance itself lives in
 * `WantedPage`, which owns selection because it renders `BulkActionBar` as a
 * sibling; the columns live here so the page and the selection tests drive the
 * same select column (#395).
 */
export function useWantedColumns() {
  const unqueueIssueMutation = useUnqueueIssue();
  const { addToast } = useToast();

  return useMemo(
    () =>
      columnHelper.columns([
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
            <Link
              to={`/library/${row.original.ComicID}`}
              className="flex min-w-0 items-baseline gap-2 underline-offset-2 hover:underline"
              onClick={(event) => event.stopPropagation()}
            >
              <span className="truncate text-sm font-medium text-foreground">
                {row.original.ComicName}
              </span>
              {row.original.ComicYear && (
                <span className="mono-meta shrink-0">
                  {row.original.ComicYear}
                </span>
              )}
            </Link>
          ),
        }),
        columnHelper.accessor("Issue_Number", {
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
        columnHelper.accessor("DateAdded", {
          header: ({ column }) => (
            <DataTableSortHeader column={column} title="Added" />
          ),
          cell: ({ getValue }) => {
            const date = getValue();
            if (!date)
              return <span className="text-muted-foreground">N/A</span>;
            return (
              <span className="font-mono text-xs text-foreground-2">
                {date}
              </span>
            );
          },
        }),
        columnHelper.accessor("IssueDate", {
          header: ({ column }) => (
            <DataTableSortHeader column={column} title="Released" />
          ),
          cell: ({ getValue }) => {
            const date = getValue();
            if (!date)
              return <span className="text-muted-foreground">N/A</span>;
            return (
              <span className="font-mono text-xs text-foreground-2">
                {date}
              </span>
            );
          },
        }),
        columnHelper.display({
          id: "acquisition",
          header: "Status",
          cell: ({ row }) => {
            const label = formatWantedAcquisitionAnnotation(
              row.original.acquisition,
            );
            const state =
              row.original.acquisition?.state?.toLowerCase() ?? null;
            const isLive = state === "accepted" || state === "running";
            const isTrouble =
              state === "no_match" ||
              state === "failed" ||
              state === "blocked" ||
              state === "quarantined";
            return (
              <span
                className="inline-flex items-center gap-1.5 text-[13px]"
                data-acquisition-state={state ?? "never"}
              >
                <span
                  aria-hidden="true"
                  className="size-1.5 shrink-0 rounded-full"
                  style={{
                    background: isLive
                      ? "var(--in-flight)"
                      : isTrouble
                        ? "var(--status-paused)"
                        : "var(--text-muted)",
                  }}
                />
                <span
                  className={
                    isLive || isTrouble
                      ? "text-foreground"
                      : "text-foreground-2"
                  }
                >
                  {label}
                </span>
              </span>
            );
          },
          enableSorting: false,
        }),
        columnHelper.display({
          id: "actions",
          header: () => <span className="sr-only">Actions</span>,
          cell: ({ row }) => (
            <Button
              size="compact"
              variant="ghost"
              onClick={(e) => {
                e.stopPropagation();
                unqueueIssueMutation.mutate(row.original.IssueID, {
                  onError: (err) => {
                    addToast({
                      type: "error",
                      message: getErrorMessage(err),
                    });
                  },
                });
              }}
              disabled={unqueueIssueMutation.isPending}
              className="text-foreground-2 opacity-60 transition-opacity group-hover/row:opacity-100 focus-visible:opacity-100"
            >
              <X />
              Skip
            </Button>
          ),
        }),
      ]),
    [addToast, unqueueIssueMutation],
  );
}
