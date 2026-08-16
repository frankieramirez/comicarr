import type { Comic } from "@/types";

/** Same-origin cover URL. Library/detail views must never hotlink provider CDNs. */
export function seriesCoverSrc(
  comicId: string | null | undefined,
): string | null {
  if (!comicId) return null;
  return `/api/metadata/art/${encodeURIComponent(comicId)}`;
}

const NON_SYNC_TIMESTAMPS = new Set(["unknown", "error", "none"]);

function isKnownRefreshTimestamp(
  value: string | null | undefined,
): value is string {
  if (value == null) return false;
  const trimmed = value.trim();
  if (!trimmed) return false;
  return !NON_SYNC_TIMESTAMPS.has(trimmed.toLowerCase());
}

/**
 * Series-detail breadcrumb label.
 *
 * `LastUpdated` is the last metadata refresh. `LatestDate` is the latest
 * *release* date (and manga import writes "Unknown" when that is missing),
 * so it must not be shown as a sync time.
 */
export function seriesSyncLabel(
  comic: Pick<Comic, "LastUpdated" | "LatestDate">,
): string {
  if (isKnownRefreshTimestamp(comic.LastUpdated)) {
    return `last sync ${comic.LastUpdated.trim()}`;
  }
  return "unsynced";
}

export function getProgressPercentage(comic: Comic): number {
  const total = parseInt(String(comic.Total)) || 0;
  const have = parseInt(String(comic.Have)) || 0;
  return total > 0 ? Math.round((have / total) * 100) : 0;
}

export function getProgressCategory(comic: Comic): "0" | "partial" | "100" {
  const percentage = getProgressPercentage(comic);
  if (percentage === 0) return "0";
  if (percentage === 100) return "100";
  return "partial";
}
