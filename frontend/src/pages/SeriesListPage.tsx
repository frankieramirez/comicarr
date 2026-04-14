import { Link } from "react-router-dom";
import { Plus } from "lucide-react";
import { useSeries } from "@/hooks/useSeries";
import SeriesTable from "@/components/series/SeriesTable";
import { Button } from "@/components/ui/button";
import ErrorDisplay from "@/components/ui/ErrorDisplay";

export default function SeriesListPage() {
  const { data: series = [], isLoading, error } = useSeries();

  if (error) {
    return (
      <ErrorDisplay
        error={error}
        title="Unable to load your library"
        onRetry={() => window.location.reload()}
      />
    );
  }

  return (
    <div className="page-transition">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-[32px] font-bold tracking-tight">My Library</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {series.length} series in your library
          </p>
        </div>
        <Link to="/search">
          <Button className="flex items-center gap-2 bg-gradient-to-r from-[#FF5C00] to-[#FF8A4C] hover:from-[#FF6A1A] hover:to-[#FF9560] text-white border-0 h-10 px-5 rounded-lg">
            <Plus className="w-[18px] h-[18px]" />
            Add to Library
          </Button>
        </Link>
      </div>

      <SeriesTable data={series} isLoading={isLoading} />
    </div>
  );
}
