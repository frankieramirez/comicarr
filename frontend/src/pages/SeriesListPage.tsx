import { Link } from "react-router-dom";
import { Plus } from "lucide-react";
import { useSeries } from "@/hooks/useSeries";
import SeriesTable from "@/components/series/SeriesTable";
import PageHeader from "@/components/layout/PageHeader";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import { Kbd } from "@/components/ui/kbd";

export default function SeriesListPage() {
  const { data: series = [], isLoading, error } = useSeries();

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

  const total = series.length;
  const mangaCount = series.filter(
    (s) => (s.ContentType || "").toLowerCase() === "manga",
  ).length;
  const comicCount = total - mangaCount;

  return (
    <div className="h-full flex flex-col page-transition">
      <PageHeader
        title="Library"
        meta={
          isLoading
            ? "loading…"
            : total === 0
              ? "0 series"
              : `${total} series · ${comicCount} comic${comicCount === 1 ? "" : "s"} · ${mangaCount} manga`
        }
        actions={
          <Link
            to="/search"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[5px] text-[12px] font-semibold"
            style={{
              background: "var(--primary)",
              color: "var(--primary-foreground)",
            }}
          >
            <Plus className="w-3.5 h-3.5" strokeWidth={2.5} />
            <span>Add</span>
            <Kbd
              className="bg-black/10! border-black/20! text-black/70!"
              style={{ color: "rgba(0,0,0,0.7)" }}
            >
              N
            </Kbd>
          </Link>
        }
      />

      {/* Table body */}
      <div className="flex-1 min-h-0 flex flex-col">
        <SeriesTable data={series} isLoading={isLoading} />
      </div>
    </div>
  );
}
