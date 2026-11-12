import { useSeries } from "@/hooks/useSeries";

/** "96 series · 56 comics · 40 manga", or a loading word. */
export function useLibrarySummary(): string {
  const { data: series = [], isLoading } = useSeries();
  if (isLoading) return "loading…";
  const total = series.length;
  if (total === 0) return "0 series";
  const manga = series.filter(
    (s) => (s.ContentType || "").toLowerCase() === "manga",
  ).length;
  const comics = total - manga;
  return `${total} series · ${comics} comic${comics === 1 ? "" : "s"} · ${manga} manga`;
}
