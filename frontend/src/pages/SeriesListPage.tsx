import { Link, useNavigate } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import LibraryTabs, {
  useLibrarySummary,
} from "@/components/series/LibraryTabs";
import { useSeries } from "@/hooks/useSeries";
import SeriesTable from "@/components/series/SeriesTable";
import PageHeader from "@/components/layout/PageHeader";
import ErrorDisplay from "@/components/ui/ErrorDisplay";

export default function SeriesListPage() {
  const { data: series = [], isLoading, error } = useSeries();
  const summary = useLibrarySummary();
  const navigate = useNavigate();

  if (error) {
    return (
      <div className="p-8">
        <h1 className="sr-only">Library</h1>
        <ErrorDisplay
          error={error}
          title="Unable to load your library"
          onRetry={() => window.location.reload()}
        />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col page-transition">
      <PageHeader
        title="Library"
        meta={summary}
        actions={
          <>
            <Button
              type="button"
              variant="outline"
              size="toolbar"
              className="bg-surface-2"
              onClick={() => navigate("/import")}
            >
              <RefreshCw />
              Scan libraries
            </Button>
            <Button size="toolbar" asChild>
              <Link to="/search" title="Add series (N)">
                <Plus />
                Add series
              </Link>
            </Button>
          </>
        }
      />
      <LibraryTabs />

      {/* Table body */}
      <div className="flex-1 min-h-0 flex flex-col pt-4">
        <SeriesTable data={series} isLoading={isLoading} />
      </div>
    </div>
  );
}
