import { ph, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Fragment, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Check, ExternalLink, ImageOff, Plus, X } from "lucide-react";
import { AiSuggestions } from "@/components/weekly/AiSuggestions";
import { Button } from "@/components/ui/button";
import FilterField from "@/components/ui/FilterField";
import FilterSelect from "@/components/ui/FilterSelect";
import StatusBadge from "@/components/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import EmptyState from "@/components/ui/EmptyState";
import { ToggleChip } from "@/components/ui/toggle-chip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useToast } from "@/components/ui/toast";
import { DESKTOP_COL } from "@/components/data-table/gridColumns";
import MangaAddDialog from "@/components/releases/MangaAddDialog";
import { describePullAttempts } from "@/components/releases/pullAttempts";
import {
  groupKey,
  matchesFormat,
  mergeReleases,
  passesPopular,
  releaseLabel,
} from "@/components/releases/industryRows";
import {
  INDUSTRY_FORMATS,
  isMangaFormat,
  releasePrefs,
  type ReleaseFormat,
} from "@/components/releases/releaseFormat";
import { useAiStatus } from "@/hooks/useAiStatus";
import { useQueueIssue } from "@/hooks/useSeries";
import { useAddFromWeek, useWeeklyPullList } from "@/hooks/useWeekly";
import { getErrorMessage } from "@/lib/api";
import { dayHeading, isoDay, parseDay, weekDays } from "@/lib/releaseWeek";
import { seriesCoverSrc } from "@/lib/series-utils";
import { statusTone } from "@/lib/statusTone";
import type { UpcomingIssue } from "@/types";
import {
  weeklyReleaseRowKey,
  type WeekRef,
  type WeeklyIssue,
  type WeeklyLibraryState,
} from "@/pages/weeklyReleaseRowKey";
import { formatDate } from "@/lib/intl";

const WEEKLY_ROW_COLS =
  "grid-cols-[minmax(0,1fr)_auto_auto] md:grid-cols-[minmax(0,1fr)_110px_160px_110px_120px]";

type SortKey = "group" | "title" | "issue";

/**
 * Badge status + label for each library state; also drives the legend. In
 * library borrows the amber Paused token so it never reads as Downloaded green.
 */
const STATE_BADGE = (): Record<
  WeeklyLibraryState,
  { status: string; label: string }
> => ({
  wanted: { status: "Wanted", label: t`Wanted` },
  downloaded: { status: "Downloaded", label: t`Downloaded` },
  in_library: { status: "Paused", label: t`In library` },
  not_in_library: { status: "Not in library", label: t`Not in library` },
});

const SORTS = (): { value: SortKey; label: string }[] => [
  { value: "group", label: t`Publisher or type` },
  { value: "title", label: t`Title` },
  { value: "issue", label: t`Issue` },
];

const ALL_PUBLISHERS = "__all__";
const WEEKDAY: Intl.DateTimeFormatOptions = { weekday: "short" };
const MANGA_GROUPS = ["manga", "manhwa", "manhua"];

function rowState(issue: WeeklyIssue): WeeklyLibraryState {
  return issue.state ?? "not_in_library";
}

function issueNumber(value: string): number {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : Number.POSITIVE_INFINITY;
}

const byTitle = (a: WeeklyIssue, b: WeeklyIssue) =>
  a.COMIC.localeCompare(b.COMIC, undefined, { sensitivity: "base" }) ||
  issueNumber(a.ISSUE) - issueNumber(b.ISSUE);

/** Comics publishers A to Z, then Manga, Manhwa, Manhua, then untyped manga. */
function groupOrder(row: WeeklyIssue): number {
  if (row.kind !== "manga") return 0;
  const index = MANGA_GROUPS.indexOf((row.mangaType ?? "").toLowerCase());
  return index === -1 ? 1 + MANGA_GROUPS.length : 1 + index;
}

const byRank = (a: WeeklyIssue, b: WeeklyIssue) =>
  (a.popular_rank ?? Number.POSITIVE_INFINITY) -
  (b.popular_rank ?? Number.POSITIVE_INFINITY);

const SORTERS: Record<SortKey, (a: WeeklyIssue, b: WeeklyIssue) => number> = {
  title: byTitle,
  group: (a, b) =>
    groupOrder(a) - groupOrder(b) ||
    groupKey(a).localeCompare(groupKey(b), undefined, {
      sensitivity: "base",
    }) ||
    // Manga groups read most popular first, like MangaUpdates' own list.
    (a.kind === "manga" ? byRank(a, b) : 0) ||
    byTitle(a, b),
  issue: (a, b) => issueNumber(a.ISSUE) - issueNumber(b.ISSUE) || byTitle(a, b),
};

function comicVineUrl(comicId: string | null): string | null {
  const id = comicId?.replace(/^4050-/, "");
  return id && /^\d+$/.test(id)
    ? `https://comicvine.gamespot.com/volume/4050-${id}/`
    : null;
}

/**
 * Releases with "Only my library" off: everything out this week (#1383).
 * Comics come from the weekly pull source, manga, manhwa and manhua from
 * MangaUpdates, and library releases neither lists are folded in so this
 * list never hides the library's own week.
 */
export default function IndustryReleasesView({
  selectedWeek,
  modeBar,
  format,
  libraryIssues,
}: {
  selectedWeek: WeekRef | null;
  /** The shared format chips and "Only my library" toggle. */
  modeBar: (counts?: Partial<Record<ReleaseFormat, number>>) => ReactNode;
  format: ReleaseFormat;
  /** The library's own releases this week, from Releases' library view. */
  libraryIssues: UpcomingIssue[];
}) {
  const { data, isLoading, error, refetch } = useWeeklyPullList(selectedWeek);
  const { data: aiStatus } = useAiStatus();
  const [filter, setFilter] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("group");
  const [publisher, setPublisher] = useState<string>(ALL_PUBLISHERS);
  const [popularOnly, setPopularOnlyState] = useState(() =>
    releasePrefs.popularOnly(),
  );
  const [day, setDay] = useState<string | null>(null);
  const manga = data?.manga;
  const mangaFormat = isMangaFormat(format);

  const setPopularOnly = (value: boolean) => {
    releasePrefs.setPopularOnly(value);
    setPopularOnlyState(value);
  };

  const all = useMemo(
    () => mergeReleases(data, libraryIssues),
    [data, libraryIssues],
  );
  // The rows every chip counts: Popular only applies before the format split.
  const listed = useMemo(
    () => all.filter((row) => passesPopular(row, popularOnly)),
    [all, popularOnly],
  );

  const formatCounts = useMemo(() => {
    const counts: Partial<Record<ReleaseFormat, number>> = {};
    for (const option of INDUSTRY_FORMATS)
      counts[option] = listed.filter((row) =>
        matchesFormat(row, option),
      ).length;
    return counts;
  }, [listed]);

  const publishers = useMemo(
    () =>
      [
        ...new Set(
          all
            .filter((row) => row.kind !== "manga")
            .map((row) => row.PUBLISHER || ""),
        ),
      ]
        .filter(Boolean)
        .sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" })),
    [all],
  );

  const beforeDay = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return listed.filter(
      (row) =>
        matchesFormat(row, format) &&
        (mangaFormat ||
          publisher === ALL_PUBLISHERS ||
          row.PUBLISHER === publisher) &&
        (!needle ||
          row.COMIC.toLowerCase().includes(needle) ||
          (row.PUBLISHER || "").toLowerCase().includes(needle)),
    );
  }, [listed, format, mangaFormat, publisher, filter]);

  // Manga ships every day, so its formats get a day strip; comics land on
  // Wednesday and would draw one tall column.
  const activeDay = mangaFormat ? day : null;
  const activeDayHeading = activeDay ? dayHeading(activeDay) : "";
  const rows = useMemo(() => {
    const matching = activeDay
      ? beforeDay.filter((row) => row.SHIPDATE?.slice(0, 10) === activeDay)
      : beforeDay;
    return [...matching].sort(SORTERS[sortKey]);
  }, [beforeDay, activeDay, sortKey]);

  if (error) {
    return (
      <ErrorDisplay
        error={error}
        title={t`Unable to load this week's releases`}
        onRetry={() => refetch()}
      />
    );
  }

  const showsManga = format === "all" || mangaFormat;
  const refreshing = manga?.status === "refreshing";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 px-4 pt-4 pb-3 md:px-8 flex items-center gap-2 flex-wrap">
        {modeBar(formatCounts)}
        <ToggleChip
          size="md"
          className="h-8"
          pressed={popularOnly}
          onPressedChange={setPopularOnly}
          title={t`Show only manga in MangaUpdates' weekly top 500, plus your own series`}
          data-testid="popular-only-toggle"
        >
          {popularOnly && <Check className="h-3.5 w-3.5" aria-hidden="true" />}
          <Trans>Popular only</Trans>
        </ToggleChip>
        <FilterField
          aria-label={t`Filter releases`}
          placeholder={t`Filter by title or publisher`}
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          widthCap="sm"
        />
        {!mangaFormat && (
          <div className="max-md:hidden">
            <FilterSelect
              label={t`Publisher`}
              value={publisher}
              options={[
                { value: ALL_PUBLISHERS, label: t`All` },
                ...publishers.map((name) => ({ value: name, label: name })),
              ]}
              onChange={setPublisher}
            />
          </div>
        )}
        <div className="ms-auto">
          <FilterSelect
            label={t`Sort`}
            value={sortKey}
            options={SORTS()}
            onChange={setSortKey}
          />
        </div>
      </div>

      {showsManga && (refreshing || manga?.error) && (
        <div
          role="status"
          className="shrink-0 px-4 pb-2 text-[13px] md:px-8"
          style={{
            color: refreshing
              ? "var(--status-active)"
              : "var(--muted-foreground)",
          }}
        >
          {refreshing
            ? t`Loading this week's manga, manhwa and manhua from MangaUpdates…`
            : manga?.error}
        </div>
      )}

      {mangaFormat && data && !isLoading && (
        <div className="shrink-0 px-4 pb-3 md:px-8">
          <DayStrip
            start={data.start}
            rows={beforeDay}
            selected={activeDay}
            onSelect={setDay}
          />
          {activeDay && (
            <div
              className="mt-2 flex items-center gap-2 text-[13px]"
              data-testid="day-filter-note"
            >
              <span className="text-foreground-2">
                <Trans>
                  Showing{" "}
                  <span className="font-medium text-foreground">
                    {activeDayHeading}
                  </span>{" "}
                  only
                </Trans>
              </span>
              <Button
                type="button"
                variant="ghost"
                size="compact"
                onClick={() => setDay(null)}
              >
                <X />
                <Trans>Show the whole week</Trans>
              </Button>
            </div>
          )}
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-auto">
        {aiStatus?.configured && data?.offset === 0 && !mangaFormat && (
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
        ) : rows.length === 0 ? (
          <EmptyWeek
            format={format}
            filtered={
              filter.trim() !== "" ||
              activeDay != null ||
              (!mangaFormat && publisher !== ALL_PUBLISHERS)
            }
            hiddenByPopular={
              (formatCounts[format] ?? 0) === 0 &&
              all.some((row) => matchesFormat(row, format))
            }
            mangaStatus={manga?.status}
            comicsSource={data?.source}
            pullReason={describePullAttempts(data?.pull_attempts)}
            future={(data?.offset ?? 0) > 0}
          />
        ) : (
          <WeeklyTable rows={rows} grouped={sortKey === "group"} />
        )}

        {showsManga && manga && manga.status !== "disabled" && (
          <p className="px-8 py-4 text-[12px] text-muted-foreground">
            <Trans>
              Manga, manhwa and manhua release data from{" "}
              <a
                href="https://www.mangaupdates.com/"
                target="_blank"
                rel="noreferrer"
                className="underline hover:text-foreground"
              >
                MangaUpdates
              </a>
              .
            </Trans>
          </p>
        )}
      </div>
    </div>
  );
}

function EmptyWeek({
  format,
  filtered,
  hiddenByPopular,
  mangaStatus,
  comicsSource,
  pullReason,
  future,
}: {
  format: ReleaseFormat;
  filtered: boolean;
  hiddenByPopular: boolean;
  mangaStatus?: string;
  comicsSource?: string;
  /** Why no source filled the week, when the server said. */
  pullReason?: string | null;
  future: boolean;
}) {
  if (filtered) {
    return (
      <EmptyState
        variant="custom"
        eyebrow={t`RELEASES · FILTERED`}
        title={t`Nothing matches that filter`}
        description={t`Clear the filter or pick another day to see the whole week.`}
      />
    );
  }
  if (hiddenByPopular) {
    return (
      <EmptyState
        variant="custom"
        eyebrow={t`RELEASES · POPULAR ONLY`}
        title={t`Nothing popular out this week`}
        description={t`Turn off Popular only to see every release MangaUpdates lists.`}
      />
    );
  }
  if (isMangaFormat(format)) {
    const description =
      mangaStatus === "disabled"
        ? t`Manga releases need a manga provider. Turn on MangaDex or MyAnimeList in Settings, then come back.`
        : mangaStatus === "refreshing"
          ? t`Comicarr is reading this week from MangaUpdates. It takes about a minute the first time.`
          : mangaStatus === "unavailable"
            ? t`MangaUpdates could not be reached. Comicarr tries again in a few minutes.`
            : future
              ? t`MangaUpdates lists chapters once they are out, so this week has no manga yet.`
              : t`MangaUpdates lists no releases of this type this week.`;
    return (
      <EmptyState
        variant="custom"
        eyebrow={t`RELEASES · EMPTY`}
        title={t`No manga releases for this week`}
        description={description}
      />
    );
  }
  return (
    <EmptyState
      variant="custom"
      eyebrow={t`RELEASES · EMPTY`}
      title={t`No releases for this week`}
      description={
        comicsSource === "unavailable"
          ? (pullReason ??
            t`No pull-list source has this week's comics yet. Future weeks fill in as publishers announce them; try again later.`)
          : t`Run a weekly pull list update from Settings to populate this view.`
      }
    />
  );
}

/** Seven days of the week with a count each; picking a day filters the list. */
function DayStrip({
  start,
  rows,
  selected,
  onSelect,
}: {
  start: string;
  rows: WeeklyIssue[];
  selected: string | null;
  onSelect: (day: string | null) => void;
}) {
  const todayKey = isoDay(new Date());
  const counts = new Map<string, number>();
  for (const row of rows) {
    const key = row.SHIPDATE?.slice(0, 10);
    if (key) counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const max = Math.max(1, ...counts.values());

  return (
    <div
      className="grid grid-cols-7 gap-1 rounded-lg border border-border-subtle bg-surface-1 p-1"
      role="group"
      aria-label={t`Releases by day this week`}
      data-testid="industry-day-strip"
    >
      {weekDays(start).map((key) => {
        const date = parseDay(key);
        const count = counts.get(key) ?? 0;
        const isSelected = selected === key;
        const isToday = key === todayKey;
        return (
          <button
            key={key}
            type="button"
            aria-pressed={isSelected}
            aria-current={isToday ? "date" : undefined}
            disabled={count === 0 && !isSelected}
            onClick={() => onSelect(isSelected ? null : key)}
            className={`min-w-0 rounded-md px-3 py-2.5 text-start max-sm:px-1.5 transition-colors enabled:hover:bg-surface-2 disabled:opacity-60 aria-pressed:bg-surface-3 aria-pressed:shadow-[inset_0_0_0_1px_var(--border-strong)] ${
              isToday ? "border border-primary" : ""
            }`}
          >
            <div className="flex items-baseline justify-between gap-2 text-[13px]">
              <span
                className={
                  isToday ? "font-medium text-foreground" : "text-foreground-2"
                }
              >
                {formatDate(date, WEEKDAY)}{" "}
                <span className="font-mono text-xs text-muted-foreground">
                  {date.getDate()}
                </span>
                {isToday && (
                  <span
                    className="ms-1.5 text-[11px] font-medium max-md:hidden"
                    style={{ color: "var(--primary)" }}
                  >
                    <Trans>Today</Trans>
                  </span>
                )}
              </span>
              <span className="font-mono text-xs text-muted-foreground max-md:hidden">
                {count}
              </span>
            </div>
            <div
              className="mt-2 h-1 rounded-full bg-surface-3"
              aria-hidden="true"
            >
              <div
                className="h-1 rounded-full"
                style={{
                  width: `${(count / max) * 100}%`,
                  background: "var(--foreground-2)",
                }}
              />
            </div>
          </button>
        );
      })}
    </div>
  );
}

/** The library's own cover first, then the source's; a placeholder when both fail. */
function Cover({ issue }: { issue: WeeklyIssue }) {
  const sources = [
    issue.in_library ? seriesCoverSrc(issue.ComicID) : null,
    issue.cover,
  ].filter((src): src is string => Boolean(src));
  const [failed, setFailed] = useState(0);
  const src = sources[failed] ?? null;
  return (
    <span className="h-10 w-7 shrink-0 overflow-hidden rounded-sm bg-muted max-md:hidden">
      {src ? (
        <img
          key={src}
          src={src}
          alt=""
          loading="lazy"
          className="h-full w-full object-cover"
          onError={() => setFailed((count) => count + 1)}
        />
      ) : (
        <span className="flex h-full w-full items-center justify-center text-muted-foreground/50">
          <ImageOff className="h-3 w-3" />
        </span>
      )}
    </span>
  );
}

function WeeklyTable({
  rows,
  grouped,
}: {
  rows: WeeklyIssue[];
  grouped: boolean;
}) {
  const [adding, setAdding] = useState<Set<string>>(() => new Set());
  const [mangaToAdd, setMangaToAdd] = useState<WeeklyIssue | null>(null);
  const addFromWeek = useAddFromWeek();
  const queueIssue = useQueueIssue();
  const queryClient = useQueryClient();
  const { addToast } = useToast();
  const groupCounts = useMemo(() => {
    const tally = new Map<string, number>();
    for (const row of rows) {
      const key = groupKey(row);
      tally.set(key, (tally.get(key) ?? 0) + 1);
    }
    return tally;
  }, [rows]);

  const add = async (issue: WeeklyIssue, want: boolean, key: string) => {
    if (issue.rowid == null) return;
    try {
      const result = await addFromWeek.mutateAsync({
        rowid: issue.rowid,
        want,
      });
      setAdding((current) => new Set(current).add(key));
      addToast({
        type: "success",
        title: t`Adding ${ph({ COMIC: issue.COMIC })}`,
        description: result.want_queued
          ? t`#${ph({ ISSUE: issue.ISSUE })} will be marked Wanted once the series is added.`
          : t`The series is being added to your library.`,
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
      queryClient.invalidateQueries({ queryKey: ["upcoming"] });
      addToast({
        type: "success",
        message: t`${ph({ series: issue.COMIC })} ${ph({ release: releaseLabel(issue) })} is Wanted.`,
      });
    } catch (err) {
      addToast({ type: "error", message: getErrorMessage(err) });
    }
  };

  return (
    <div data-testid="weekly-releases-table">
      <div
        className={`sticky top-0 z-10 grid ${WEEKLY_ROW_COLS} gap-x-2 md:gap-x-3 mx-4 md:mx-8 px-2 h-8 items-center border-b border-border-subtle bg-background text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground`}
      >
        <div className="md:ps-10">
          <Trans>title</Trans>
        </div>
        <div className={DESKTOP_COL}>
          <Trans>release</Trans>
        </div>
        <div className={DESKTOP_COL}>
          <Trans>publisher / type</Trans>
        </div>
        <div>
          <span className="max-md:hidden">
            <Trans>in your library</Trans>
          </span>
          <span className="md:hidden">
            <Trans>status</Trans>
          </span>
        </div>
        <div className="text-end">
          <span className="sr-only">
            <Trans>actions</Trans>
          </span>
        </div>
      </div>
      {rows.map((issue, index) => {
        const key = weeklyReleaseRowKey(issue, index);
        const state = rowState(issue);
        const badge = STATE_BADGE()[state];
        const isAdding = adding.has(key);
        const group = groupKey(issue);
        const startsGroup =
          grouped && (index === 0 || groupKey(rows[index - 1]) !== group);
        const label = releaseLabel(issue);
        return (
          <Fragment key={key}>
            {startsGroup && (
              <div
                className="mx-4 md:mx-8 flex h-9 items-center gap-2 border-b border-border-subtle px-2 pt-2 text-[13px] font-semibold"
                data-testid="weekly-publisher-group"
              >
                {group}
                <span className="mono-meta font-normal">
                  {groupCounts.get(group)}
                </span>
              </div>
            )}
            <div
              data-testid="weekly-release-row"
              data-kind={issue.kind ?? "comic"}
              className={`group/row grid ${WEEKLY_ROW_COLS} gap-x-2 md:gap-x-3 items-center mx-4 md:mx-8 px-2 py-1.5 min-h-9 text-[13px] border-b border-border-subtle hover:bg-surface-1`}
            >
              <div
                className="flex min-w-0 items-center gap-3 font-medium"
                data-grid-title=""
              >
                <Cover issue={issue} />
                <span className="min-w-0 truncate">
                  <ReleaseTitle issue={issue} />
                  {label ? (
                    <span
                      data-testid="phone-row-id"
                      className="hidden max-md:inline font-mono text-[11px]"
                      style={{ color: "var(--muted-foreground)" }}
                    >
                      {" "}
                      {label}
                    </span>
                  ) : null}
                </span>
              </div>
              <div
                className={`${DESKTOP_COL} font-mono text-[13px] text-foreground-2 truncate`}
              >
                {label}
              </div>
              <div className={`${DESKTOP_COL} text-foreground-2 truncate`}>
                {issue.kind === "manga"
                  ? issue.mangaType || t`Manga`
                  : issue.PUBLISHER}
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
                  <span className="mono-meta">
                    <Trans>adding…</Trans>
                  </span>
                ) : state === "not_in_library" && issue.kind === "manga" ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="compact"
                    aria-label={t`Add ${ph({ COMIC: issue.COMIC })}`}
                    onClick={() => setMangaToAdd(issue)}
                  >
                    <Plus />
                    <Trans>Add</Trans>
                  </Button>
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
                          aria-label={t`Add ${ph({ COMIC: issue.COMIC })}`}
                          disabled={addFromWeek.isPending}
                        />
                      }
                    >
                      <Plus />
                      <Trans>Add</Trans>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" sideOffset={4}>
                      <DropdownMenuItem
                        onClick={() => void add(issue, false, key)}
                      >
                        <Trans>Add series</Trans>
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onClick={() => void add(issue, true, key)}
                      >
                        {t`Add series and want #${ph({ issue: issue.ISSUE })}`}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : state === "in_library" && issue.library_issue_id ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="compact"
                    aria-label={t`Want ${ph({ COMIC: issue.COMIC })} ${label}`}
                    disabled={queueIssue.isPending}
                    onClick={() => void want(issue)}
                  >
                    <Trans>Want</Trans>
                  </Button>
                ) : null}
              </div>
            </div>
          </Fragment>
        );
      })}
      {mangaToAdd && (
        <MangaAddDialog
          title={mangaToAdd.COMIC}
          onClose={() => setMangaToAdd(null)}
        />
      )}
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
  const external =
    issue.kind === "manga" ? issue.url || null : comicVineUrl(issue.ComicID);
  if (external) {
    return (
      <a
        href={external}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1 hover:underline"
        title={
          issue.kind === "manga" ? "Open on MangaUpdates" : "Open on ComicVine"
        }
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
