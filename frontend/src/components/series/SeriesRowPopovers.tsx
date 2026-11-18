import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useState, type ReactElement, type ReactNode } from "react";
import StatusBadge from "@/components/StatusBadge";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { useSeriesDetail } from "@/hooks/useSeries";
import { formatDate, formatNumber } from "@/lib/intl";
import { seriesCoverSrc } from "@/lib/series-utils";
import type { Comic } from "@/types";
import { MangaCoverageStrip } from "./MangaVolumes";

/**
 * The Library list's two row popovers. Both open on hover; the Have count is
 * also a button, so a tap or the keyboard opens it too.
 */

function Line({
  label,
  value,
  color,
  faded,
}: {
  label: string;
  value: string;
  /** A swatch matching the series page's coverage colors. */
  color?: string;
  /** The lighter swatch the coverage bar uses for chapters inside a volume. */
  faded?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="flex items-center gap-1.5 text-foreground-2">
        {color ? (
          <span
            aria-hidden="true"
            className="inline-block size-2 shrink-0 rounded-sm"
            style={{ background: color, opacity: faded ? 0.5 : undefined }}
          />
        ) : null}
        {label}
      </dt>
      <dd className="font-mono tabular-nums">{value}</dd>
    </div>
  );
}

function HaveBreakdownBody({ comicId }: { comicId: string }) {
  const { data, isPending, isError } = useSeriesDetail(comicId);

  if (isPending) {
    return (
      <div className="space-y-2" data-testid="have-breakdown-loading">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-4/5" />
        <Skeleton className="h-3 w-3/5" />
      </div>
    );
  }
  const progress = data?.manga?.progress;
  if (isError || !progress) {
    return (
      <p className="text-muted-foreground">
        <Trans>The breakdown could not be loaded.</Trans>
      </p>
    );
  }

  const number = (value: number | undefined) => formatNumber(value ?? 0);
  const inFlight = data?.summary?.inFlight ?? 0;
  const volumesOwned = formatNumber(progress.volumesOwned);
  const volumesTotal = formatNumber(progress.volumesTotal);
  const chapterFiles = progress.chaptersOwned;
  return (
    <>
      <dl className="space-y-1.5">
        <Line
          label={t`Volumes`}
          value={t`${volumesOwned} of ${volumesTotal}`}
        />
        <Line
          label={t`Chapters inside those volumes`}
          value={number(data?.summary?.covered)}
          color="var(--status-downloaded)"
          faded
        />
        <Line
          label={t`Chapter files`}
          value={number(chapterFiles)}
          color="var(--status-downloaded)"
        />
        {inFlight > 0 && (
          <Line
            label={t`Downloading`}
            value={number(inFlight)}
            color="var(--in-flight)"
          />
        )}
        {progress.chaptersGap > 0 && (
          <Line
            label={t`Missing before your latest chapter`}
            value={number(progress.chaptersGap)}
            color="var(--status-paused)"
          />
        )}
      </dl>
      {progress.segments.length > 0 && (
        <MangaCoverageStrip
          progress={progress}
          className="mt-3 h-1.5"
          label={t`${volumesOwned} of ${volumesTotal} volumes, ${chapterFiles} chapter files`}
        />
      )}
    </>
  );
}

/**
 * A manga series' Have count as a button that opens what the number is made
 * of: volume files and chapter files. A comic's count needs no breakdown.
 */
export function HaveBreakdown({
  comic,
  children,
}: {
  comic: Comic;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const name = comic.ComicName;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        openOnHover
        delay={150}
        closeDelay={100}
        aria-label={t`What you have of ${name}`}
        data-testid="have-breakdown-trigger"
        className="-mx-1.5 rounded-sm px-1.5 py-0.5 font-mono text-xs tabular-nums hover:bg-surface-2 data-popup-open:bg-surface-2"
        onClick={(event) => event.stopPropagation()}
      >
        {children}
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-72 p-3 text-xs"
        data-testid="have-breakdown"
        // A click inside the popover must not open the row's series.
        onClick={(event) => event.stopPropagation()}
      >
        {open ? <HaveBreakdownBody comicId={comic.ComicID} /> : null}
      </PopoverContent>
    </Popover>
  );
}

function releaseDate(value: string | null | undefined): string | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}/.test(value)) return null;
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return null;
  return formatDate(date, { dateStyle: "medium" });
}

/** The series title with a preview card: cover, what it is, and where it stands. */
export function SeriesTitlePreview({
  comic,
  kindLabel,
  children,
}: {
  comic: Comic;
  kindLabel: string;
  /** The title link; it stays the way into the series. */
  children: ReactElement;
}) {
  const cover = seriesCoverSrc(comic.ComicID);
  const [coverFailed, setCoverFailed] = useState(false);
  const wanted = Number(comic.Wanted) || 0;
  const latest = releaseDate(comic.LatestDate);
  const meta = [comic.ComicPublisher, comic.ComicYear]
    .filter(Boolean)
    .join(" · ");
  return (
    <HoverCard openDelay={400} closeDelay={100}>
      <HoverCardTrigger asChild>{children}</HoverCardTrigger>
      <HoverCardContent
        align="start"
        className="w-96 p-3 text-xs"
        data-testid="series-title-preview"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex gap-3">
          {cover && !coverFailed ? (
            <img
              src={cover}
              alt=""
              className="h-[132px] w-[88px] shrink-0 rounded-sm bg-surface-2 object-cover"
              onError={() => setCoverFailed(true)}
            />
          ) : null}
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-medium leading-snug">
              {comic.ComicName}
            </div>
            <div className="mt-0.5 text-muted-foreground">
              {[kindLabel, meta].filter(Boolean).join(" · ")}
            </div>
            <div className="mt-1.5">
              <StatusBadge
                variant="dot"
                status={(comic.Status || "unknown").toLowerCase()}
              />
            </div>
            {comic.Description ? (
              <p className="mt-2 line-clamp-4 leading-relaxed text-foreground-2">
                {comic.Description}
              </p>
            ) : null}
          </div>
        </div>
        {(wanted > 0 || latest) && (
          <dl className="mt-3 space-y-1.5 border-t border-border-subtle pt-2.5">
            {wanted > 0 && (
              <Line label={t`Wanted`} value={formatNumber(wanted)} />
            )}
            {latest && <Line label={t`Latest release`} value={latest} />}
          </dl>
        )}
      </HoverCardContent>
    </HoverCard>
  );
}
