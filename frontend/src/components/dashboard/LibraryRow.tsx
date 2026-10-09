import { PanelUnavailable } from "@/components/dashboard/DashboardPanel";
import { useDashboardLibrary } from "@/hooks/useDashboard";
import { panelState } from "@/lib/panelState";

/**
 * What the library is, as one row of numbers
 * (docs/architecture/dashboard-spec.md §3.6).
 *
 * It used to be three hero KPI tiles at the top of the page, which read as a
 * vanity panel and pushed the only actionable content below the fold. It is
 * ambient — it never changes what the operator does today — so it sits below
 * the actionable panels and below the timeline, and renders at body size.
 *
 * `completion_pct` keeps its definition (`total_issues / total_expected`) but
 * is labelled as what it is: issues held vs. issues known. It is not a health
 * metric, and the layout keeps it away from the health band, where adjacency
 * alone would make it read as one.
 */
export default function LibraryRow() {
  const library = useDashboardLibrary();
  const state = panelState(library, false);
  const stats = library.data?.stats;

  if (state === "loading") {
    return (
      <div className="px-5 py-3.5 border-b border-border">
        <div
          aria-hidden="true"
          className="h-3 w-64 animate-pulse rounded-sm bg-primary/10"
        />
      </div>
    );
  }

  if (state === "unavailable") {
    return (
      <div className="px-5 border-b border-border">
        <PanelUnavailable
          label="Library"
          onRetry={() => void library.refetch()}
          isRetrying={library.isFetching}
        />
      </div>
    );
  }

  const series = stats?.total_series ?? 0;
  const issues = stats?.total_issues ?? 0;
  const completion = stats?.completion_pct ?? 0;

  return (
    <div
      className="px-5 py-3.5 border-b border-border flex flex-wrap items-center gap-x-2 gap-y-1"
      data-testid="library-row"
    >
      <span className="text-[14px]">
        <span className="font-semibold">{series.toLocaleString()}</span>{" "}
        <span className="text-muted-foreground">series</span>
      </span>
      <span className="text-border" aria-hidden="true">
        ·
      </span>
      <span className="text-[14px]">
        <span className="font-semibold">{issues.toLocaleString()}</span>{" "}
        <span className="text-muted-foreground">issues held</span>
      </span>
      <span className="text-border" aria-hidden="true">
        ·
      </span>
      <span className="text-[14px]">
        <span className="font-semibold">{completion.toFixed(1)}%</span>{" "}
        <span className="text-muted-foreground">of known issues held</span>
      </span>
      <span className="ml-auto font-mono text-[11px] text-muted-foreground">
        not a health metric
      </span>
    </div>
  );
}
