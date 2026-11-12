import { useState } from "react";
import { Link } from "react-router-dom";
import { ImageOff } from "lucide-react";
import {
  PanelBody,
  PanelSkeleton,
  SectionHeader,
} from "@/components/dashboard/DashboardPanel";
import { useSeries } from "@/hooks/useSeries";
import { panelState } from "@/lib/panelState";
import { seriesCoverSrc } from "@/lib/series-utils";
import type { Comic } from "@/types";

/**
 * The two library sections of the v2 dashboard's main column: the newest
 * series as covers, and the series with the most missing issues.
 *
 * Both derive from the same `GET /api/series` read the Library page uses, so
 * they share its cache and can never disagree with it.
 */

const RECENT_COUNT = 6;
const WANTED_COUNT = 3;

function count(value: unknown): number {
  return parseInt(String(value ?? 0), 10) || 0;
}

function Cover({ comic }: { comic: Comic }) {
  const [failed, setFailed] = useState(false);
  const src = seriesCoverSrc(comic.ComicID);
  return (
    <div className="aspect-[2/3] overflow-hidden rounded-md bg-surface-2">
      {src && !failed ? (
        <img
          src={src}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
          className="size-full object-cover transition-transform duration-200 group-hover:scale-[1.03]"
        />
      ) : (
        <div className="flex size-full items-center justify-center text-muted-foreground">
          <ImageOff className="size-6" />
        </div>
      )}
    </div>
  );
}

export function RecentlyAdded() {
  const series = useSeries();
  const recent = [...(series.data ?? [])]
    .filter((comic) => comic.DateAdded)
    .sort((a, b) => String(b.DateAdded).localeCompare(String(a.DateAdded)))
    .slice(0, RECENT_COUNT);
  const state = panelState(series, recent.length === 0);

  return (
    <section data-testid="recently-added">
      <SectionHeader
        title="Recently added"
        action={{ label: "Open library", to: "/library" }}
      />
      <PanelBody
        state={state}
        label="Recently added"
        skeleton={<PanelSkeleton rows={1} rowHeight={180} />}
        empty="No series yet. Add one from the search box."
        onRetry={() => void series.refetch()}
        isRetrying={series.isFetching}
      >
        {() => (
          <div className="grid grid-cols-3 gap-4 sm:grid-cols-6">
            {recent.map((comic) => (
              <Link
                key={comic.ComicID}
                to={`/library/${comic.ComicID}`}
                className="group min-w-0"
              >
                <Cover comic={comic} />
                <div className="mt-2 truncate text-[13px] text-foreground">
                  {comic.ComicName}
                </div>
                <div className="mono-meta">
                  {count(comic.Have)} / {count(comic.Total)}
                </div>
              </Link>
            ))}
          </div>
        )}
      </PanelBody>
    </section>
  );
}

export function MostWanted() {
  const series = useSeries();
  const ranked = (series.data ?? [])
    .map((comic) => ({
      comic,
      missing: Math.max(0, count(comic.Total) - count(comic.Have)),
    }))
    .filter(
      ({ comic, missing }) =>
        missing > 0 && String(comic.Status).toLowerCase() !== "paused",
    )
    .sort((a, b) => b.missing - a.missing);
  const top = ranked.slice(0, WANTED_COUNT);
  const totalMissing = ranked.reduce((sum, row) => sum + row.missing, 0);
  const state = panelState(series, top.length === 0);

  return (
    <section data-testid="most-wanted">
      <SectionHeader
        title="Most wanted"
        meta={
          state === "content"
            ? `${totalMissing.toLocaleString()} issues across ${ranked.length} series`
            : undefined
        }
        action={{ label: "Open Wanted", to: "/wanted" }}
      />
      <PanelBody
        state={state}
        label="Most wanted"
        skeleton={<PanelSkeleton rows={3} rowHeight={36} />}
        empty="Every series is complete."
        onRetry={() => void series.refetch()}
        isRetrying={series.isFetching}
      >
        {() => (
          <div className="border-t border-border-subtle">
            {top.map(({ comic, missing }) => (
              <Link
                key={comic.ComicID}
                to={`/library/${comic.ComicID}`}
                className="flex h-9 items-center gap-3 border-b border-border-subtle px-2 text-sm hover:bg-surface-1"
              >
                <span className="min-w-0 flex-1 truncate">
                  {comic.ComicName}
                </span>
                <span className="font-mono text-xs text-foreground-2">
                  {missing} missing
                </span>
              </Link>
            ))}
          </div>
        )}
      </PanelBody>
    </section>
  );
}
