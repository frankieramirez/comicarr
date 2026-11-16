import { plural, t } from "@lingui/core/macro";
import { useSeries } from "@/hooks/useSeries";

/** "96 series · 56 comics · 40 manga", or a loading word. */
export function useLibrarySummary(): string {
  const { data: series = [], isLoading } = useSeries();
  if (isLoading) return t`loading…`;
  const total = series.length;
  if (total === 0) return t`0 series`;
  const manga = series.filter(
    (s) => (s.ContentType || "").toLowerCase() === "manga",
  ).length;
  const comics = total - manga;
  const seriesCount = plural(total, { one: "# series", other: "# series" });
  const comicCount = plural(comics, { one: "# comic", other: "# comics" });
  const mangaCount = plural(manga, { one: "# manga", other: "# manga" });
  return t`${seriesCount} · ${comicCount} · ${mangaCount}`;
}
