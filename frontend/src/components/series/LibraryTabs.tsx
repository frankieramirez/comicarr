import { t } from "@lingui/core/macro";
import { useLocation, useNavigate } from "react-router-dom";
import { Tab, TabRow } from "@/components/layout/PageHeader";
import { useSeries } from "@/hooks/useSeries";
import { useShelfEnabled } from "@/hooks/useShelf";
import { useStoryArcs } from "@/hooks/useStoryArcs";

/**
 * Series and Story arcs share the Library page. Story arcs are frozen for
 * 1.0, so they live here as a secondary view instead of in the sidebar. The
 * Shelf tab appears once "Track print copies" is switched on in Settings.
 */
export default function LibraryTabs() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const series = useSeries();
  const arcs = useStoryArcs();
  const shelfEnabled = useShelfEnabled();
  const onArcs = pathname.startsWith("/story-arcs");
  const onShelf = pathname.startsWith("/shelf");

  return (
    <TabRow ariaLabel={t`Library views`}>
      <Tab
        active={!onArcs && !onShelf}
        label={t`Series`}
        meta={series.data?.length}
        onClick={() => navigate("/library")}
      />
      <Tab
        active={onArcs}
        label={t`Story arcs`}
        meta={arcs.data?.length}
        onClick={() => navigate("/story-arcs")}
      />
      {shelfEnabled || onShelf ? (
        <Tab
          active={onShelf}
          label={t`Shelf`}
          onClick={() => navigate("/shelf")}
        />
      ) : null}
    </TabRow>
  );
}
