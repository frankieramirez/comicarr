import { plural, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useState, type FormEvent } from "react";
import StatusBadge from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { useSetMangaVolumeEnd } from "@/hooks/useSeries";
import { formatNumber } from "@/lib/intl";
import { SEGMENTED_GROUP, SEGMENTED_ITEM } from "@/lib/segmented";
import type { MangaCoverageKind, MangaProgress, MangaVolume } from "@/types";

/**
 * Manga series: what you can read, as volumes and chapters (ADR-0004).
 *
 * The coverage bar runs from chapter 1 to the latest. Green is a chapter you
 * have, solid for its own file and lighter when it is inside a volume file.
 * Amber is a hole below the highest chapter you have.
 */

const KIND_COLOR: Record<MangaCoverageKind, string> = {
  chapter: "var(--status-downloaded)",
  // Lighter than a chapter file through opacity (KIND_OPACITY).
  volume: "var(--status-downloaded)",
  inFlight: "var(--in-flight)",
  gap: "var(--status-paused)",
  wanted: "var(--status-wanted)",
  notWanted: "var(--surface-3)",
};

const KIND_OPACITY: Partial<Record<MangaCoverageKind, number>> = {
  volume: 0.5,
};

function kindLabel(kind: MangaCoverageKind): string {
  switch (kind) {
    case "volume":
      return t`Inside a volume you have`;
    case "chapter":
      return t`Chapter files`;
    case "inFlight":
      return t`Downloading`;
    case "gap":
      return t`Missing before your latest chapter`;
    case "wanted":
      return t`Wanted`;
    case "notWanted":
      return t`Not wanted`;
  }
}

function segmentRange(from: string, to: string): string {
  return from === to ? t`ch ${from}` : t`ch ${from}–${to}`;
}

export function MangaCoverageBar({ progress }: { progress: MangaProgress }) {
  const segments = progress.segments;
  const kinds = Array.from(new Set(segments.map((segment) => segment.kind)));
  const order: MangaCoverageKind[] = [
    "volume",
    "chapter",
    "inFlight",
    "gap",
    "wanted",
    "notWanted",
  ];
  const lastChapter = segments.length ? segments[segments.length - 1].to : null;
  const volumesOwned = progress.volumesOwned;
  const volumesTotal = progress.volumesTotal;
  const chapterFiles = progress.chaptersOwned;
  const summary = t`${volumesOwned} of ${volumesTotal} volumes, ${chapterFiles} chapter files`;
  return (
    <div className="mt-5" data-testid="manga-coverage">
      <dl className="flex flex-wrap gap-x-7 gap-y-2">
        <Stat
          value={`${formatNumber(progress.volumesOwned)} / ${formatNumber(progress.volumesTotal)}`}
          label={t`volumes`}
        />
        <Stat
          value={formatNumber(progress.chaptersOwned)}
          label={t`chapter files`}
        />
        {progress.chaptersGap > 0 && (
          <Stat
            value={formatNumber(progress.chaptersGap)}
            label={t`missing before your latest chapter`}
            color="var(--status-paused)"
          />
        )}
      </dl>
      <div
        className="mt-3 flex h-2.5 overflow-hidden rounded-full bg-surface-3"
        role="img"
        aria-label={summary}
      >
        {segments.map((segment) => (
          <div
            key={`${segment.kind}-${segment.from}`}
            title={`${kindLabel(segment.kind)}: ${segmentRange(segment.from, segment.to)}`}
            style={{
              flexGrow: segment.count,
              background: KIND_COLOR[segment.kind],
              opacity: KIND_OPACITY[segment.kind],
            }}
          />
        ))}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        {order
          .filter((kind) => kinds.includes(kind))
          .map((kind) => (
            <span key={kind} className="inline-flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className="inline-block size-2 rounded-sm"
                style={{
                  background: KIND_COLOR[kind],
                  opacity: KIND_OPACITY[kind],
                }}
              />
              {kindLabel(kind)}
            </span>
          ))}
        {lastChapter && (
          <span className="mono-meta ms-auto">
            <Trans>ch 1–{lastChapter}</Trans>
          </span>
        )}
      </div>
    </div>
  );
}

function Stat({
  value,
  label,
  color,
}: {
  value: string;
  label: string;
  color?: string;
}) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="sr-only">{label}</dt>
      <dd
        className="font-mono text-[15px] font-semibold"
        style={color ? { color } : undefined}
      >
        {value}
      </dd>
      <span aria-hidden="true" className="text-[12px] text-muted-foreground">
        {label}
      </span>
    </div>
  );
}

type VolumeFilter = "all" | "have" | "missing";

export const VOLUME_GRID_COLS =
  "grid-cols-[56px_minmax(0,1fr)_auto] md:grid-cols-[56px_200px_minmax(160px,1fr)_120px_100px]";

export function MangaVolumeList({
  comicId,
  volumes,
  progress,
}: {
  comicId: string;
  volumes: MangaVolume[];
  progress: MangaProgress;
}) {
  const [filter, setFilter] = useState<VolumeFilter>("all");
  const [editing, setEditing] = useState<string | null>(null);
  const have = volumes.filter((volume) => volume.owned).length;
  const counts = {
    all: volumes.length,
    have,
    missing: volumes.length - have,
  };
  const shown = volumes.filter(
    (volume) => filter === "all" || volume.owned === (filter === "have"),
  );
  const estimated = progress.volumesEstimated;

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="manga-volumes">
      <div className="flex shrink-0 flex-wrap items-center gap-3 px-8 py-3">
        <div
          role="group"
          aria-label={t`Filter volumes`}
          className={SEGMENTED_GROUP}
        >
          {(
            [
              ["all", t`All`],
              ["have", t`Have`],
              ["missing", t`Missing`],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              aria-pressed={filter === key}
              aria-label={`${label} ${counts[key]}`}
              onClick={() => setFilter(key)}
              className={SEGMENTED_ITEM}
            >
              {label}
              <span className="mono-meta">{counts[key]}</span>
            </button>
          ))}
        </div>
      </div>

      {estimated > 0 && (
        <div className="mx-8 mb-3">
          <Callout tone="warning" data-testid="manga-volume-estimates">
            {plural(estimated, {
              one: "MangaDex doesn't list the chapters for # volume, so its range is estimated from the volumes around it. A volume you have covers the chapters in its range. If a range is off, set the chapter that volume ends at.",
              other:
                "MangaDex doesn't list the chapters for # volumes, so their ranges are estimated from the volumes around them. A volume you have covers the chapters in its range. If a range is off, set the chapter that volume ends at.",
            })}
          </Callout>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto pb-6">
        <div
          className={`sticky top-0 z-10 grid ${VOLUME_GRID_COLS} h-8 items-center gap-3 border-b border-border-subtle bg-background mx-8 px-2 text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground`}
        >
          <div>
            <Trans>vol</Trans>
          </div>
          <div>
            <Trans>chapters</Trans>
          </div>
          <div className="max-md:hidden">
            <Trans>file</Trans>
          </div>
          <div className="max-md:hidden">
            <Trans>state</Trans>
          </div>
          <div className="sr-only">
            <Trans>actions</Trans>
          </div>
        </div>
        {shown.length === 0 ? (
          <div className="px-5 py-8 text-center mono-meta">
            <Trans>no volumes to display</Trans>
          </div>
        ) : (
          shown.map((volume) => (
            <VolumeRow
              key={volume.number}
              comicId={comicId}
              volume={volume}
              editing={editing === volume.number}
              onEdit={(open) => setEditing(open ? volume.number : null)}
            />
          ))
        )}
      </div>
    </div>
  );
}

function RangeText({ volume }: { volume: MangaVolume }) {
  if (!volume.firstChapter || !volume.lastChapter) {
    return (
      <span className="text-muted-foreground">
        <Trans>unknown</Trans>
      </span>
    );
  }
  const range =
    volume.firstChapter === volume.lastChapter
      ? volume.firstChapter
      : `${volume.firstChapter}–${volume.lastChapter}`;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="font-mono">{range}</span>
      {volume.rangeSource === "estimated" && (
        <span
          className="rounded-sm border border-dashed px-1 text-[10px]"
          style={{
            borderColor: "var(--status-paused)",
            color: "var(--status-paused)",
          }}
          title={t`MangaDex doesn't list this volume's chapters`}
        >
          <Trans>estimated</Trans>
        </span>
      )}
      {volume.rangeSource === "user" && (
        <span className="text-[10px] text-muted-foreground">
          <Trans>set by you</Trans>
        </span>
      )}
    </span>
  );
}

function VolumeRow({
  comicId,
  volume,
  editing,
  onEdit,
}: {
  comicId: string;
  volume: MangaVolume;
  editing: boolean;
  onEdit: (open: boolean) => void;
}) {
  const setEnd = useSetMangaVolumeEnd();
  const { addToast } = useToast();
  const [last, setLast] = useState(volume.lastChapter ?? "");
  const number = volume.number;

  const save = async (lastChapter: string | null) => {
    try {
      await setEnd.mutateAsync({ comicId, volume: number, lastChapter });
      onEdit(false);
    } catch {
      addToast({
        type: "error",
        title: t`Error`,
        description: t`Couldn't update volume ${number}`,
      });
    }
  };

  return (
    <div
      className="mx-8 border-b border-border-subtle px-2 py-1 text-[13px] hover:bg-surface-1"
      data-testid={`manga-volume-${number}`}
    >
      <div className={`grid ${VOLUME_GRID_COLS} min-h-9 items-center gap-3`}>
        <div className="font-mono">{number}</div>
        <div className="min-w-0">
          <RangeText volume={volume} />
        </div>
        <div className="min-w-0 truncate mono-meta max-md:hidden">
          {volume.location ?? "—"}
        </div>
        <div className="max-md:hidden">
          {volume.owned ? (
            <StatusBadge status="downloaded" label={t`Have`} variant="dot" />
          ) : volume.inFlight ? (
            <StatusBadge status="snatched" variant="dot" />
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </div>
        <div className="flex justify-end">
          <Button
            type="button"
            variant="ghost"
            size="toolbar"
            aria-expanded={editing}
            aria-label={t`Edit the chapters in volume ${number}`}
            onClick={() => onEdit(!editing)}
          >
            <Trans>Edit range</Trans>
          </Button>
        </div>
      </div>
      {editing && (
        <form
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            void save(last);
          }}
          className="flex flex-wrap items-center gap-2 pb-2 ps-[68px]"
        >
          <label className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
            <Trans>Ends at chapter</Trans>
            <Input
              inputMode="decimal"
              className="h-7 w-20"
              value={last}
              onChange={(event) => setLast(event.target.value)}
            />
          </label>
          <Button
            type="submit"
            size="toolbar"
            disabled={setEnd.isPending || !last}
          >
            <Trans>Save</Trans>
          </Button>
          {volume.rangeSource === "user" && (
            <Button
              type="button"
              variant="ghost"
              size="toolbar"
              disabled={setEnd.isPending}
              onClick={() => void save(null)}
            >
              <Trans>Use MangaDex or estimate</Trans>
            </Button>
          )}
        </form>
      )}
    </div>
  );
}
