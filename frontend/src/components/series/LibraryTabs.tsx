import { useLocation, useNavigate } from "react-router-dom";
import { Tab, TabRow } from "@/components/layout/PageHeader";
import { useSeries } from "@/hooks/useSeries";
import { useStoryArcs } from "@/hooks/useStoryArcs";

/**
 * Series and Story arcs share the Library page. Story arcs are frozen for
 * 1.0, so they live here as a secondary view instead of in the sidebar.
 */
export default function LibraryTabs() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const series = useSeries();
  const arcs = useStoryArcs();
  const onArcs = pathname.startsWith("/story-arcs");

  return (
    <TabRow ariaLabel="Library views">
      <Tab
        active={!onArcs}
        label="Series"
        meta={series.data?.length}
        onClick={() => navigate("/library")}
      />
      <Tab
        active={onArcs}
        label="Story arcs"
        meta={arcs.data?.length}
        onClick={() => navigate("/story-arcs")}
      />
    </TabRow>
  );
}

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
