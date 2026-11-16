import { ph, plural, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
/**
 * Timeline tab — Variant A (Ledger) chrome.
 *
 * Absolute HH:MM gutter, severity dots (green open / red closed-in-trouble /
 * else none), sentence + RelativeTime, sticky day rules, page size 25 stories.
 * Always-collapsed; group-of-one is a plain row. Filters: free-text + activity
 * segmented kind filter (band owns needs-attention).
 */

import { SEGMENTED_GROUP, SEGMENTED_ITEM } from "@/lib/segmented";
import { Fragment, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import EmptyState from "@/components/ui/EmptyState";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import FilterField from "@/components/ui/FilterField";
import RelativeTime from "@/components/ui/RelativeTime";
import { Skeleton } from "@/components/ui/skeleton";
import { useActivityBand, useActivityTimeline } from "@/hooks/useActivity";
import { AttentionBand } from "./AttentionBand";
import {
  actorLabel,
  reasonDetailLine,
  runProgress,
  storyHeadline,
} from "./sentences";
import {
  buildFeed,
  clockOf,
  dayKey,
  dayLabel,
  isOpen,
  subjectHref,
  storyHasTrouble,
} from "./stories";
import type { Story } from "./types";

const STORY_PAGE_SIZE = 25;

/** The segmented filter: what kind of thing happened, not which producer. */
const FILTERS = () =>
  [
    { key: "all", label: t`All`, activities: null },
    { key: "failures", label: t`Failures`, activities: null },
    {
      key: "downloads",
      label: t`Downloads`,
      activities: ["search", "grab", "download"],
    },
    {
      key: "library",
      label: t`Library`,
      activities: ["import", "refresh", "add", "tag", "status_change"],
    },
  ] as const;

type FilterKey = ReturnType<typeof FILTERS>[number]["key"];

const ROW_COLS =
  "grid-cols-[44px_minmax(0,1fr)_auto] md:grid-cols-[48px_minmax(0,1.3fr)_minmax(0,1fr)_72px]";

function SeverityDot({ open, trouble }: { open: boolean; trouble: boolean }) {
  if (open) {
    return (
      <span
        role="img"
        aria-label={t`In progress`}
        className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full"
        style={{ background: "var(--status-active)" }}
      />
    );
  }
  if (trouble) {
    return (
      <span
        role="img"
        aria-label={t`Needs attention (history)`}
        className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full"
        style={{ background: "var(--status-error)" }}
      />
    );
  }
  return (
    <span
      aria-hidden
      className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full"
      style={{ background: "transparent" }}
    />
  );
}

function Headline({ story }: { story: Story }) {
  const text = storyHeadline(story);
  const href = subjectHref(story);
  const label = story.subject_label;

  if (!href || !label || story.subject_type === "run") {
    return <span>{text}</span>;
  }

  const idx = text.indexOf(label);
  if (idx < 0) {
    return (
      <span>
        {text}{" "}
        <Link to={href} className="font-medium hover:text-[var(--primary)]">
          {label}
        </Link>
      </span>
    );
  }

  return (
    <span>
      {text.slice(0, idx)}
      <Link to={href} className="font-medium hover:text-[var(--primary)]">
        {label}
      </Link>
      {text.slice(idx + label.length)}
    </span>
  );
}

function DetailLine({ story }: { story: Story }) {
  const closer = story.closer;
  // Who asked, when it wasn't Comicarr: the first event that names an actor.
  const actor =
    story.events.map(actorLabel).find((label) => label !== null) ?? null;
  // A status change already names its new status in the sentence, and run
  // rows carry their counts as JSON in reason_detail, which the sentence
  // already says; neither repeats it here.
  const line =
    closer && closer.activity !== "status_change"
      ? reasonDetailLine(
          closer.reason_code,
          story.subject_type === "run" ? null : closer.reason_detail,
        )
      : null;
  if (!line?.phrase && !line?.detail) {
    return actor ? <div className="mono-meta truncate">{actor}</div> : null;
  }
  return (
    <div className="truncate text-[12px] text-foreground-2">
      {line.phrase}
      {line.rawCode && <span className="mono-meta ml-2">{line.rawCode}</span>}
      {line.detail && <span className="mono-meta ml-2">{line.detail}</span>}
      {actor && <span className="mono-meta ml-2">{actor}</span>}
    </div>
  );
}

function FirstRunEmpty({ scoped }: { scoped: boolean }) {
  return (
    <div className="px-8 py-10">
      <EmptyState
        variant="custom"
        eyebrow={
          scoped ? t`TIMELINE · SCOPED · EMPTY` : t`TIMELINE · NOTHING YET`
        }
        title={
          scoped
            ? t`No activity for this scope yet`
            : t`Nothing has happened yet`
        }
        description={
          scoped
            ? t`Searches, grabs and imports for this series or issue will show up here as they happen.`
            : t`Add a series and mark issues as wanted — searches, grabs and imports will show up here as they happen.`
        }
        action={
          scoped
            ? { label: t`Back to all activity`, to: "/activity" }
            : { label: t`Add a series`, to: "/search" }
        }
      />
    </div>
  );
}

export function TimelineView({
  scope_type,
  scope_id,
}: {
  scope_type?: string | null;
  scope_id?: string | null;
}) {
  const [query, setQuery] = useState("");
  const [activity, setActivity] = useState<FilterKey>("all");
  const [page, setPage] = useState(0);

  const timeline = useActivityTimeline({ scope_type, scope_id });
  const band = useActivityBand({ scope_type, scope_id });

  const bandGroups = band.data?.results ?? [];
  const events = useMemo(
    () => timeline.data?.pages.flatMap((p) => p.results) ?? [],
    [timeline.data?.pages],
  );

  const nodes = useMemo(() => buildFeed(events), [events]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return nodes.filter((story) => {
      if (activity === "failures" && !storyHasTrouble(story)) return false;
      const wanted = FILTERS().find((f) => f.key === activity)?.activities;
      if (wanted) {
        const kinds: readonly string[] = wanted;
        if (!story.events.some((e) => kinds.includes(e.activity))) return false;
      }
      if (!q) return true;
      return (
        story.subject_label.toLowerCase().includes(q) ||
        storyHeadline(story).toLowerCase().includes(q)
      );
    });
  }, [nodes, query, activity]);

  const start = page * STORY_PAGE_SIZE;
  const pageNodes = filtered.slice(start, start + STORY_PAGE_SIZE);
  const hasMoreStories = start + STORY_PAGE_SIZE < filtered.length;
  const hasMoreEvents = Boolean(timeline.hasNextPage);

  const isInitialLoading =
    (timeline.isLoading || band.isLoading) && !timeline.data && !band.data;
  const hardError =
    !timeline.data && !band.data ? (timeline.error ?? band.error) : null;

  const scoped = Boolean(scope_type?.trim()) && Boolean(scope_id?.trim());

  if (isInitialLoading) {
    return (
      <div className="space-y-2 px-8 py-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-11" />
        ))}
      </div>
    );
  }

  if (hardError) {
    return (
      <div className="px-8 py-4">
        <ErrorDisplay
          error={hardError}
          title={t`Unable to load activity timeline`}
          onRetry={() => {
            void timeline.refetch();
            void band.refetch();
          }}
        />
      </div>
    );
  }

  if (nodes.length === 0 && bandGroups.length === 0) {
    return (
      <>
        {scoped && (
          <div className="px-8 py-2 mono-meta">
            <Trans>
              Scoped to {scope_type}:{scope_id}
            </Trans>
          </div>
        )}
        <FirstRunEmpty scoped={scoped} />
      </>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <AttentionBand
        groups={bandGroups}
        total={band.data?.total ?? bandGroups.length}
        memberTotal={band.data?.member_total ?? bandGroups.length}
        previewCap={band.data?.preview_cap ?? 5}
        scope_type={scope_type}
        scope_id={scope_id}
      />

      {scoped && (
        <div className="flex shrink-0 items-center gap-2 px-8 py-2 mono-meta">
          <span>
            <Trans>
              Scoped to {scope_type}:{scope_id}
            </Trans>
          </span>
          <Link to="/activity" className="ml-auto hover:text-foreground">
            <Trans>clear scope</Trans>
          </Link>
        </div>
      )}

      <div className="flex shrink-0 flex-wrap items-center gap-3 px-8 pt-1 pb-3">
        <div
          role="group"
          aria-label={t`Filter by activity`}
          className={SEGMENTED_GROUP}
        >
          {FILTERS().map((f) => (
            <button
              key={f.key}
              type="button"
              aria-pressed={activity === f.key}
              onClick={() => {
                setActivity(f.key);
                setPage(0);
              }}
              className={SEGMENTED_ITEM}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="max-w-sm flex-1">
          <FilterField
            placeholder={t`Filter timeline…`}
            aria-label={t`Filter timeline`}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(0);
            }}
            shortcut="/"
          />
        </div>
      </div>

      <div
        role="feed"
        aria-label={t`Activity timeline`}
        className="flex-1 min-h-0 overflow-auto"
      >
        {pageNodes.length > 0 && (
          <div
            className={`sticky top-0 z-20 mx-8 grid ${ROW_COLS} h-8 items-center gap-x-3 border-b border-border-subtle bg-background px-2 text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground`}
            aria-hidden="true"
          >
            <span>
              <Trans>Time</Trans>
            </span>
            <span>
              <Trans>Event</Trans>
            </span>
            <span className="max-md:hidden">
              <Trans>Detail</Trans>
            </span>
            <span className="max-md:hidden" />
          </div>
        )}
        {pageNodes.map((story, index) => {
          const prev = pageNodes[index - 1];
          const showDay =
            !prev || dayKey(prev.opened_at) !== dayKey(story.opened_at);
          const open = isOpen(story);
          const trouble = storyHasTrouble(story);
          const multi = story.events.length > 1;

          return (
            <Fragment key={story.key}>
              {showDay && (
                <div className="sticky top-8 z-10 mx-8 border-b border-border-subtle bg-surface-1 px-2 py-1.5 text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">
                  {dayLabel(story.opened_at)}
                </div>
              )}

              <div
                className={`mx-8 grid ${ROW_COLS} min-h-9 items-center gap-x-3 border-b border-border-subtle px-2 py-1.5 hover:bg-surface-1`}
              >
                <span className="font-mono text-[12px] tabular-nums text-muted-foreground">
                  {clockOf(story.opened_at)}
                </span>

                <div className="flex min-w-0 items-start gap-2">
                  <SeverityDot open={open} trouble={trouble} />
                  <div className="min-w-0 text-[13px] leading-snug">
                    <Headline story={story} />
                    {runProgress(story) && (
                      <span className="ml-2 mono-meta">
                        {runProgress(story)}
                      </span>
                    )}
                    {multi && (
                      <span
                        className="mono-meta ml-2"
                        title={plural(story.events.length, {
                          one: "# event in this story",
                          other: "# events in this story",
                        })}
                      >
                        ×{story.events.length}
                      </span>
                    )}
                    <div className="md:hidden">
                      <DetailLine story={story} />
                    </div>
                  </div>
                </div>

                <div className="min-w-0 max-md:hidden">
                  <DetailLine story={story} />
                </div>

                <span className="text-right">
                  <RelativeTime value={story.opened_at} compact />
                </span>
              </div>
            </Fragment>
          );
        })}

        {pageNodes.length === 0 && (
          <div className="px-8 py-8">
            <EmptyState
              variant="custom"
              eyebrow={
                nodes.length === 0
                  ? t`TIMELINE · EMPTY`
                  : t`TIMELINE · FILTERED`
              }
              title={
                nodes.length === 0
                  ? t`No timeline events yet`
                  : t`Nothing matches`
              }
              description={
                nodes.length === 0
                  ? t`Items that need you stay above until you act on them.`
                  : t`Try a different filter.`
              }
            />
          </div>
        )}
      </div>

      {(filtered.length > 0 || hasMoreEvents) && (
        <div className="flex shrink-0 items-center gap-3 border-t border-border-subtle px-8 py-2.5">
          <span className="mono-meta">
            {filtered.length === 0
              ? t`0 stories`
              : hasMoreEvents
                ? t`${ph({ first: start + 1 })}–${ph({ last: Math.min(start + STORY_PAGE_SIZE, filtered.length) })} of ${ph({ total: filtered.length })}+ stories`
                : t`${ph({ first: start + 1 })}–${ph({ last: Math.min(start + STORY_PAGE_SIZE, filtered.length) })} of ${ph({ total: filtered.length })} stories`}
          </span>
          <div className="ml-auto flex gap-1.5">
            <button
              type="button"
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
              className="h-7 rounded-md border border-border-strong px-2.5 text-[13px] text-foreground-2 hover:bg-surface-2 disabled:opacity-40"
            >
              <Trans>Previous</Trans>
            </button>
            <button
              type="button"
              disabled={
                (!hasMoreStories && !hasMoreEvents) ||
                timeline.isFetchingNextPage
              }
              onClick={() => {
                if (hasMoreStories) {
                  setPage((p) => p + 1);
                  return;
                }
                if (hasMoreEvents) {
                  void timeline.fetchNextPage();
                }
              }}
              className="h-7 rounded-md border border-border-strong px-2.5 text-[13px] text-foreground-2 hover:bg-surface-2 disabled:opacity-40"
            >
              {timeline.isFetchingNextPage
                ? t`Loading…`
                : hasMoreStories
                  ? t`Next`
                  : t`Older`}
            </button>
          </div>
        </div>
      )}
      <p className="mono-meta shrink-0 px-8 pb-4">
        <Trans>
          older than 90 days is deleted · History keeps the full ledger
        </Trans>
      </p>
    </div>
  );
}
