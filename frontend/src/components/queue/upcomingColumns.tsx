import { ph, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useMemo } from "react";
import { createColumnHelper } from "@tanstack/react-table";
import {
  BookOpen,
  CircleDot,
  Download,
  FileText,
  MoreHorizontal,
  Wrench,
  X,
} from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
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
  /** The setup gap that stops every search ("no indexer"), if there is one. */
  searchPaused: string | null = null,
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
            aria-label={t`Select all rows`}
            checked={getIsAllSelected(table)}
            onCheckedChange={(value) => toggleAllSelected(table, !!value)}
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            aria-label={t`Select ${ph({ series: row.original.ComicName ?? "" })}`}
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
        header: t`Series`,
        cell: ({ row }) => (
          // On phones the zero width keeps a long name from widening the
          // table past the screen and pushing the row menu off it, so the
          // name truncates in whatever space is left.
          <div className="flex min-w-0 items-center gap-2 max-md:w-0 max-md:min-w-full">
            <Link
              to={`/library/${row.original.ComicID}`}
              className="truncate text-sm font-medium text-foreground hover:underline underline-offset-2"
              onClick={(event) => event.stopPropagation()}
            >
              {row.original.ComicName}
            </Link>
            {row.original.ContentType && (
              <span className="shrink-0 rounded-md border border-border-strong px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.04em] text-muted-foreground max-md:hidden">
                {row.original.ContentType === "manga" ? t`Manga` : t`Comic`}
              </span>
            )}
          </div>
        ),
        enableSorting: false,
        // With the zero-width name above, the full width sends every spare
        // pixel to the name instead of spreading it across the columns.
        meta: { cellClassName: "max-md:w-full" },
      }),
      columnHelper.display({
        id: "IssueNumber",
        header: t`Issue`,
        cell: ({ row }) => (
          <span className="whitespace-nowrap font-mono text-[13px] text-foreground">
            {releaseNumber(row.original)}
          </span>
        ),
        size: 90,
      }),
      columnHelper.accessor((row) => row.Publisher ?? "", {
        id: "Publisher",
        header: t`Publisher`,
        cell: ({ getValue }) => (
          <span className="block max-w-[180px] truncate text-[13px] text-foreground-2">
            {getValue() || "—"}
          </span>
        ),
        enableSorting: false,
      }),
      columnHelper.display({
        id: "Status",
        header: () => (
          <span className="max-md:sr-only">
            <Trans>Status</Trans>
          </span>
        ),
        cell: ({ row }) => {
          const state = releaseState(
            row.original,
            today,
            undefined,
            searchPaused,
          );
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
              {state.bucket === "needs_you" && !state.setupBlocked ? (
                <Link
                  to={`/library/${row.original.ComicID}/issue/${row.original.IssueID}`}
                  className="text-muted-foreground hover:text-foreground hover:underline underline-offset-2 max-md:hidden"
                  onClick={(event) => event.stopPropagation()}
                >
                  <Trans>· see why</Trans>
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
        header: () => (
          <span className="sr-only">
            <Trans>Actions</Trans>
          </span>
        ),
        cell: ({ row }) => {
          const issue = row.original;
          const status = issue.Status?.toLowerCase();
          const issueId = issue.IssueID;
          const fix =
            issue.attention && issue.attention_reason
              ? fixes?.get(issue.attention_reason)
              : undefined;
          // A pull-list row can arrive before the series refresh creates its
          // issue; without an IssueID there is nothing to search, and the
          // button used to do nothing at all.
          const canReview =
            status === "wanted" && !!onReview && !!issueId && !searchPaused;
          const canSkip = status === "wanted";
          const canWant =
            status === "skipped" ||
            (status !== "wanted" &&
              status !== "downloaded" &&
              status !== "snatched");
          const review = () => onReview?.(issue);
          const skip = () =>
            unqueueIssueMutation.mutate(issueId, {
              onSuccess: () =>
                addToast({ type: "success", message: t`1 issue skipped` }),
              onError: reportMutationError,
            });
          const want = () =>
            queueIssueMutation.mutate(issueId, {
              onSuccess: () =>
                addToast({ type: "success", message: t`1 issue queued` }),
              onError: reportMutationError,
            });
          const issueHref = issueId
            ? `/library/${issue.ComicID}/issue/${issueId}`
            : null;

          return (
            <div className="flex items-center justify-end gap-1">
              {/* Desktop: the actions sit on the row, brightening on hover. */}
              <div className="flex items-center justify-end gap-1 opacity-70 transition-opacity group-hover/row:opacity-100 focus-within:opacity-100 max-md:hidden">
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
                {canReview && (
                  <Button
                    size="compact"
                    variant="ghost"
                    onClick={(event) => {
                      event.stopPropagation();
                      review();
                    }}
                    className="text-foreground-2"
                  >
                    <CircleDot />
                    <Trans>Review releases</Trans>
                  </Button>
                )}
                {canSkip && (
                  <Button
                    size="compact"
                    variant="ghost"
                    onClick={(event) => {
                      event.stopPropagation();
                      skip();
                    }}
                    disabled={unqueueIssueMutation.isPending}
                    className="text-foreground-2"
                  >
                    <X />
                    <Trans>Skip</Trans>
                  </Button>
                )}
                {canWant && (
                  <Button
                    size="compact"
                    variant="ghost"
                    onClick={(event) => {
                      event.stopPropagation();
                      want();
                    }}
                    disabled={queueIssueMutation.isPending}
                    className="text-foreground-2"
                  >
                    <Download />
                    <Trans>Want</Trans>
                  </Button>
                )}
              </div>
              {/* Phones have no room for a row of buttons, so the same
                  actions, plus a way into the issue, live in one menu (#1508). */}
              <DropdownMenu>
                <DropdownMenuTrigger
                  aria-label={t`Actions for ${ph({ series: issue.ComicName ?? "" })} ${ph({ release: releaseNumber(issue) })}`}
                  onClick={(event) => event.stopPropagation()}
                  className={cn(
                    buttonVariants({ variant: "ghost", size: "icon" }),
                    "-me-2 size-10 text-foreground-2 md:hidden",
                  )}
                >
                  <MoreHorizontal />
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="end"
                  className="min-w-[12rem] [&_[role=menuitem]]:py-2.5"
                >
                  {fix && (
                    <DropdownMenuItem render={<Link to={fix.href} />}>
                      <Wrench />
                      {fix.label}
                    </DropdownMenuItem>
                  )}
                  {canReview && (
                    <DropdownMenuItem onClick={review}>
                      <CircleDot />
                      <Trans>Review releases</Trans>
                    </DropdownMenuItem>
                  )}
                  {canWant && (
                    <DropdownMenuItem
                      onClick={want}
                      disabled={queueIssueMutation.isPending}
                    >
                      <Download />
                      <Trans>Want</Trans>
                    </DropdownMenuItem>
                  )}
                  {canSkip && (
                    <DropdownMenuItem
                      onClick={skip}
                      disabled={unqueueIssueMutation.isPending}
                    >
                      <X />
                      <Trans>Skip</Trans>
                    </DropdownMenuItem>
                  )}
                  {(fix || canReview || canWant || canSkip) && (
                    <DropdownMenuSeparator />
                  )}
                  {issueHref && (
                    <DropdownMenuItem render={<Link to={issueHref} />}>
                      <FileText />
                      <Trans>Open issue</Trans>
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuItem
                    render={<Link to={`/library/${issue.ComicID}`} />}
                  >
                    <BookOpen />
                    <Trans>Open series</Trans>
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
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
    searchPaused,
    today,
    unqueueIssueMutation,
  ]);
}
