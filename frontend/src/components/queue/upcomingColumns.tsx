import { useMemo } from "react";
import { createColumnHelper } from "@tanstack/react-table";
import { CircleDot, Download, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Link } from "react-router-dom";
import { CoverCell } from "@/components/data-table/cells/CoverCell";
import {
  type ComicarrTableFeatures,
  getIsAllSelected,
  toggleAllSelected,
} from "@/components/data-table/useTableState";
import { useToast } from "@/components/ui/toast";
import { useQueueIssue, useUnqueueIssue } from "@/hooks/useSeries";
import { getErrorMessage } from "@/lib/api";
import { releaseNumber, releaseState } from "@/lib/releaseState";
import { isoDay } from "@/lib/releaseWeek";
import type { UpcomingIssue } from "@/types";

const columnHelper = createColumnHelper<ComicarrTableFeatures, UpcomingIssue>();

/**
 * Columns for the Upcoming table. The table instance itself lives in
 * `ReleasesPage`'s `MyReleasesView`, which owns selection because it renders
 * `BulkActionBar` as a sibling; the columns live here so the page and the
 * selection tests drive the same select column (#395).
 */
export function useUpcomingColumns(
  onReview?: (issue: UpcomingIssue) => void,
  today: string = isoDay(new Date()),
  /** Needs attention base reason to the one place that fixes it. */
  fixes?: ReadonlyMap<string, { label: string; href: string }>,
) {
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
            <CoverCell
              comicId={row.original.ComicID}
              isManga={row.original.ContentType === "manga"}
            />
          </div>
        ),
        size: 44,
        enableSorting: false,
      }),
      columnHelper.accessor("ComicName", {
        header: "Series",
        cell: ({ row }) => (
          <div className="flex min-w-0 items-center gap-2">
            <Link
              to={`/library/${row.original.ComicID}`}
              className="truncate text-sm font-medium text-foreground hover:underline underline-offset-2"
              onClick={(event) => event.stopPropagation()}
            >
              {row.original.ComicName}
            </Link>
            {row.original.ContentType && (
              <span className="shrink-0 rounded-md border border-border-strong px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.04em] text-muted-foreground max-md:hidden">
                {row.original.ContentType === "manga" ? "Manga" : "Comic"}
              </span>
            )}
          </div>
        ),
        enableSorting: false,
      }),
      columnHelper.display({
        id: "IssueNumber",
        header: "Issue",
        cell: ({ row }) => (
          <span className="whitespace-nowrap font-mono text-[13px] text-foreground">
            {releaseNumber(row.original)}
          </span>
        ),
        size: 90,
      }),
      columnHelper.accessor((row) => row.Publisher ?? "", {
        id: "Publisher",
        header: "Publisher",
        cell: ({ getValue }) => (
          <span className="block max-w-[180px] truncate text-[13px] text-foreground-2">
            {getValue() || "—"}
          </span>
        ),
        enableSorting: false,
      }),
      columnHelper.display({
        id: "Status",
        header: () => <span className="max-md:sr-only">Status</span>,
        cell: ({ row }) => {
          const state = releaseState(row.original, today);
          return (
            <span className="inline-flex min-w-0 items-center gap-2 whitespace-nowrap text-[13px]">
              <span
                data-testid="status-dot"
                aria-hidden="true"
                className="size-1.5 shrink-0 rounded-full"
                style={{ background: state.tone }}
              />
              {/* Phones keep only the dot; the label stays for screen readers. */}
              <span className="text-foreground max-md:sr-only">
                {state.label}
              </span>
              {state.progress != null && (
                <span
                  role="progressbar"
                  aria-label={`${state.label} ${state.progress}%`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={state.progress}
                  className="inline-flex items-center gap-2 max-md:hidden"
                >
                  <span className="h-1 w-14 overflow-hidden rounded-full bg-surface-3">
                    <span
                      className="block h-full rounded-full"
                      style={{
                        width: `${Math.max(2, state.progress)}%`,
                        background: "var(--in-flight)",
                      }}
                    />
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {state.progress}%
                  </span>
                </span>
              )}
              {state.bucket === "needs_you" ? (
                <Link
                  to={`/library/${row.original.ComicID}/issue/${row.original.IssueID}`}
                  className="text-muted-foreground hover:text-foreground hover:underline underline-offset-2 max-md:hidden"
                  onClick={(event) => event.stopPropagation()}
                >
                  · see why
                </Link>
              ) : state.detail ? (
                <span className="font-mono text-xs text-muted-foreground max-md:hidden">
                  {state.detail}
                </span>
              ) : null}
            </span>
          );
        },
      }),
      columnHelper.display({
        id: "actions",
        header: () => <span className="sr-only">Actions</span>,
        cell: ({ row }) => {
          const status = row.original.Status?.toLowerCase();
          const issueId = row.original.IssueID;
          const fix =
            row.original.attention && row.original.attention_reason
              ? fixes?.get(row.original.attention_reason)
              : undefined;

          return (
            <div className="flex items-center justify-end gap-1 opacity-70 transition-opacity group-hover/row:opacity-100 focus-within:opacity-100">
              {fix && (
                <Button
                  size="compact"
                  variant="outline"
                  asChild
                  className="opacity-100"
                >
                  <Link
                    to={fix.href}
                    onClick={(event) => event.stopPropagation()}
                  >
                    {fix.label}
                  </Link>
                </Button>
              )}
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
  }, [
    addToast,
    fixes,
    onReview,
    queueIssueMutation,
    today,
    unqueueIssueMutation,
  ]);
}
