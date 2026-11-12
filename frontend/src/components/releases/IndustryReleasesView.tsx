import { SEGMENTED_GROUP, SEGMENTED_ITEM } from "@/lib/segmented";
import { Fragment, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Plus } from "lucide-react";
import { AiSuggestions } from "@/components/weekly/AiSuggestions";
import { Button } from "@/components/ui/button";
import FilterField from "@/components/ui/FilterField";
import FilterSelect from "@/components/ui/FilterSelect";
import StatusBadge from "@/components/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import EmptyState from "@/components/ui/EmptyState";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useToast } from "@/components/ui/toast";
import { DESKTOP_COL } from "@/components/data-table/gridColumns";
import { useAiStatus } from "@/hooks/useAiStatus";
import { useQueueIssue } from "@/hooks/useSeries";
import { useAddFromWeek, useWeeklyPullList } from "@/hooks/useWeekly";
import { getErrorMessage } from "@/lib/api";
import { statusTone } from "@/lib/statusTone";
import {
  weeklyReleaseRowKey,
  type WeekRef,
  type WeeklyIssue,
  type WeeklyLibraryState,
} from "@/pages/weeklyReleaseRowKey";

const WEEKLY_ROW_COLS =
  "grid-cols-[minmax(0,1fr)_auto_auto] md:grid-cols-[minmax(0,1fr)_80px_160px_110px_120px]";

type SortKey = "title" | "publisher" | "issue";

/**
 * Badge status + label for each library state; also drives the legend. In
 * library borrows the amber Paused token so it never reads as Downloaded green.
 */
const STATE_BADGE: Record<
  WeeklyLibraryState,
  { status: string; label: string }
> = {
  wanted: { status: "Wanted", label: "Wanted" },
  downloaded: { status: "Downloaded", label: "Downloaded" },
  in_library: { status: "Paused", label: "In library" },
  not_in_library: { status: "Not in library", label: "Not in library" },
};

type FollowFilter = "all" | "following" | "not_following";

const FOLLOW_FILTERS: { key: FollowFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "following", label: "Following" },
  { key: "not_following", label: "Not following" },
];

const SORTS: { value: SortKey; label: string }[] = [
  { value: "publisher", label: "Publisher" },
  { value: "title", label: "Title" },
  { value: "issue", label: "Issue" },
];

const ALL_PUBLISHERS = "__all__";

function rowState(issue: WeeklyIssue): WeeklyLibraryState {
  return issue.state ?? "not_in_library";
}

function isFollowing(issue: WeeklyIssue): boolean {
  return rowState(issue) !== "not_in_library";
}

function issueNumber(value: string): number {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : Number.POSITIVE_INFINITY;
}

const byTitle = (a: WeeklyIssue, b: WeeklyIssue) =>
  a.COMIC.localeCompare(b.COMIC, undefined, { sensitivity: "base" }) ||
  issueNumber(a.ISSUE) - issueNumber(b.ISSUE);

const SORTERS: Record<SortKey, (a: WeeklyIssue, b: WeeklyIssue) => number> = {
  title: byTitle,
  publisher: (a, b) =>
    (a.PUBLISHER || "").localeCompare(b.PUBLISHER || "", undefined, {
      sensitivity: "base",
    }) || byTitle(a, b),
  issue: (a, b) => issueNumber(a.ISSUE) - issueNumber(b.ISSUE) || byTitle(a, b),
};

function comicVineUrl(comicId: string | null): string | null {
  const id = comicId?.replace(/^4050-/, "");
  return id && /^\d+$/.test(id)
    ? `https://comicvine.gamespot.com/volume/4050-${id}/`
    : null;
}

export default function IndustryReleasesView({
  selectedWeek,
}: {
  selectedWeek: WeekRef | null;
}) {
  const { data, isLoading, error, refetch } = useWeeklyPullList(selectedWeek);
  const { data: aiStatus } = useAiStatus();
  const [filter, setFilter] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("publisher");
  const [follow, setFollow] = useState<FollowFilter>("all");

  const [publisher, setPublisher] = useState<string>(ALL_PUBLISHERS);

  const publishers = useMemo(
    () =>
      [...new Set((data?.rows ?? []).map((row) => row.PUBLISHER || ""))]
        .filter(Boolean)
        .sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" })),
    [data],
  );

  const rows = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const matching = (data?.rows ?? []).filter(
      (row) =>
        (follow === "all" || (follow === "following") === isFollowing(row)) &&
        (publisher === ALL_PUBLISHERS || row.PUBLISHER === publisher) &&
        (!needle ||
          row.COMIC.toLowerCase().includes(needle) ||
          (row.PUBLISHER || "").toLowerCase().includes(needle)),
    );
    return [...matching].sort(SORTERS[sortKey]);
  }, [data, filter, follow, publisher, sortKey]);

  const counts = useMemo(() => {
    const all = data?.rows ?? [];
    const following = all.filter(isFollowing).length;
    return {
      all: all.length,
      following,
      not_following: all.length - following,
    } satisfies Record<FollowFilter, number>;
  }, [data]);

  if (error) {
    return (
      <ErrorDisplay
        error={error}
        title="Unable to load weekly pull list"
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 px-8 pt-4 pb-3 flex items-center gap-2 flex-wrap">
        <div
          className={SEGMENTED_GROUP}
          role="group"
          aria-label="Following"
          data-testid="weekly-legend"
        >
          {FOLLOW_FILTERS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              aria-pressed={follow === key}
              onClick={() => setFollow(key)}
              className={SEGMENTED_ITEM}
            >
              {label} <span className="mono-meta">{counts[key]}</span>
            </button>
          ))}
        </div>
        <FilterField
          aria-label="Filter releases"
          placeholder="Filter by title or publisher"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          widthCap="sm"
        />
        <div className="max-md:hidden">
          <FilterSelect
            label="Publisher"
            value={publisher}
            options={[
              { value: ALL_PUBLISHERS, label: "All" },
              ...publishers.map((name) => ({ value: name, label: name })),
            ]}
            onChange={setPublisher}
          />
        </div>
        <div className="ml-auto">
          <FilterSelect
            label="Sort"
            value={sortKey}
            options={SORTS}
            onChange={setSortKey}
          />
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-auto">
        {aiStatus?.configured && data?.offset === 0 && (
          <div className="px-8 py-4">
            <AiSuggestions />
          </div>
        )}

        {isLoading ? (
          <div className="px-8 py-4 space-y-2">
            {Array.from({ length: 10 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : !data || data.rows.length === 0 ? (
          <EmptyState
            variant="custom"
            eyebrow="PULL LIST · EMPTY"
            title="No pull list for this week"
            description={
              data?.source === "unavailable"
                ? "Neither Walksoftly nor ComicVine has this week yet. Future weeks fill in as publishers announce them; try again later."
                : "Run a weekly pull list update from Settings to populate this view."
            }
          />
        ) : rows.length === 0 ? (
          <EmptyState
            variant="custom"
            eyebrow="PULL LIST · FILTERED"
            title="Nothing matches that filter"
            description="Clear the filter to see the whole week."
          />
        ) : (
          <WeeklyTable rows={rows} grouped={sortKey === "publisher"} />
        )}
      </div>
    </div>
  );
}

function WeeklyTable({
  rows,
  grouped,
}: {
  rows: WeeklyIssue[];
  grouped: boolean;
}) {
  const [adding, setAdding] = useState<Set<number>>(() => new Set());
  const addFromWeek = useAddFromWeek();
  const queueIssue = useQueueIssue();
  const queryClient = useQueryClient();
  const { addToast } = useToast();
  const groupCounts = useMemo(() => {
    const tally = new Map<string, number>();
    for (const row of rows) {
      const key = row.PUBLISHER || "Unknown publisher";
      tally.set(key, (tally.get(key) ?? 0) + 1);
    }
    return tally;
  }, [rows]);

  const add = async (issue: WeeklyIssue, want: boolean) => {
    if (issue.rowid == null) return;
    const rowid = issue.rowid;
    try {
      const result = await addFromWeek.mutateAsync({ rowid, want });
      setAdding((current) => new Set(current).add(rowid));
      addToast({
        type: "success",
        title: `Adding ${issue.COMIC}`,
        description: result.want_queued
          ? `#${issue.ISSUE} will be marked Wanted once the series is added.`
          : "The series is being added to your library.",
      });
    } catch (err) {
      addToast({ type: "error", message: getErrorMessage(err) });
    }
  };

  const want = async (issue: WeeklyIssue) => {
    if (!issue.library_issue_id) return;
    try {
      await queueIssue.mutateAsync(issue.library_issue_id);
      queryClient.invalidateQueries({ queryKey: ["weekly"] });
      addToast({
        type: "success",
        message: `${issue.COMIC} #${issue.ISSUE} is Wanted.`,
      });
    } catch (err) {
      addToast({ type: "error", message: getErrorMessage(err) });
    }
  };

  return (
    <div data-testid="weekly-releases-table">
      <div
        className={`sticky top-0 z-10 grid ${WEEKLY_ROW_COLS} gap-x-2 md:gap-x-3 mx-8 px-2 h-8 items-center border-b border-border-subtle bg-background text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground`}
      >
        <div>title</div>
        <div className={DESKTOP_COL}>issue</div>
        <div className={DESKTOP_COL}>publisher</div>
        <div>
          <span className="max-md:hidden">in your library</span>
          <span className="md:hidden">status</span>
        </div>
        <div className="text-right">
          <span className="sr-only">actions</span>
        </div>
      </div>
      {rows.map((issue, index) => {
        const state = rowState(issue);
        const badge = STATE_BADGE[state];
        const isAdding = issue.rowid != null && adding.has(issue.rowid);
        const publisher = issue.PUBLISHER || "Unknown publisher";
        const startsGroup =
          grouped &&
          (index === 0 ||
            (rows[index - 1].PUBLISHER || "Unknown publisher") !== publisher);
        return (
          <Fragment key={weeklyReleaseRowKey(issue, index)}>
            {startsGroup && (
              <div
                className="mx-8 flex h-9 items-center gap-2 border-b border-border-subtle px-2 pt-2 text-[13px] font-semibold"
                data-testid="weekly-publisher-group"
              >
                {publisher}
                <span className="mono-meta font-normal">
                  {groupCounts.get(publisher)}
                </span>
              </div>
            )}
            <div
              data-testid="weekly-release-row"
              className={`group/row grid ${WEEKLY_ROW_COLS} gap-x-2 md:gap-x-3 items-center mx-8 px-2 py-1.5 min-h-9 text-[13px] border-b border-border-subtle hover:bg-surface-1`}
            >
              <div className="font-medium truncate" data-grid-title="">
                <ReleaseTitle issue={issue} />
                {issue.ISSUE ? (
                  <span
                    data-testid="phone-row-id"
                    className="hidden max-md:inline font-mono text-[11px]"
                    style={{ color: "var(--muted-foreground)" }}
                  >
                    {" "}
                    #{issue.ISSUE}
                  </span>
                ) : null}
              </div>
              <div
                className={`${DESKTOP_COL} font-mono text-[13px] text-foreground-2`}
              >
                #{issue.ISSUE}
              </div>
              <div className={`${DESKTOP_COL} text-foreground-2 truncate`}>
                {issue.PUBLISHER}
              </div>
              <div>
                {/* Phones keep only the dot so the title holds half the row. */}
                <span
                  role="img"
                  aria-label={badge.label}
                  title={badge.label}
                  className="md:hidden inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: statusTone(badge.status)?.token }}
                />
                <span className={DESKTOP_COL}>
                  {state === "not_in_library" ? (
                    <span
                      className="text-muted-foreground"
                      aria-label={badge.label}
                      title={badge.label}
                    >
                      —
                    </span>
                  ) : (
                    <StatusBadge
                      variant="dot"
                      status={badge.status}
                      label={badge.label}
                    />
                  )}
                </span>
              </div>
              <div className="flex justify-end">
                {isAdding ? (
                  <span className="mono-meta">adding…</span>
                ) : state === "not_in_library" &&
                  issue.ComicID &&
                  issue.rowid != null ? (
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      render={
                        <Button
                          type="button"
                          variant="outline"
                          size="compact"
                          aria-label={`Add ${issue.COMIC}`}
                          disabled={addFromWeek.isPending}
                        />
                      }
                    >
                      <Plus />
                      Add
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" sideOffset={4}>
                      <DropdownMenuItem onClick={() => void add(issue, false)}>
                        Add series
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => void add(issue, true)}>
                        Add series and want #{issue.ISSUE}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : state === "in_library" && issue.library_issue_id ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="compact"
                    aria-label={`Want ${issue.COMIC} #${issue.ISSUE}`}
                    disabled={queueIssue.isPending}
                    onClick={() => void want(issue)}
                  >
                    Want
                  </Button>
                ) : null}
              </div>
            </div>
          </Fragment>
        );
      })}
    </div>
  );
}

function ReleaseTitle({ issue }: { issue: WeeklyIssue }) {
  if (issue.in_library && issue.ComicID) {
    return (
      <Link to={`/library/${issue.ComicID}`} className="hover:underline">
        {issue.COMIC}
      </Link>
    );
  }
  const external = comicVineUrl(issue.ComicID);
  if (external) {
    return (
      <a
        href={external}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1 hover:underline"
        title="Open on ComicVine"
      >
        {issue.COMIC}
        <ExternalLink
          className="h-3 w-3 shrink-0"
          style={{ color: "var(--muted-foreground)" }}
          aria-hidden="true"
        />
      </a>
    );
  }
  return <>{issue.COMIC}</>;
}
