import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Link, useNavigate } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import LibraryTabs from "@/components/series/LibraryTabs";
import { useLibrarySummary } from "@/hooks/useLibrarySummary";
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
        <h1 className="sr-only">
          <Trans>Library</Trans>
        </h1>
        <ErrorDisplay
          error={error}
          title={t`Unable to load your library`}
          onRetry={() => window.location.reload()}
        />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col page-transition">
      <PageHeader
        title={t`Library`}
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
              <Trans>Scan libraries</Trans>
            </Button>
            <Button size="toolbar" asChild>
              <Link to="/search" title={t`Add series (N)`}>
                <Plus />
                <Trans>Add series</Trans>
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
