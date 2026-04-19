import { Link } from "react-router-dom";
import { Plus, Search as SearchIcon } from "lucide-react";
import { useSeries } from "@/hooks/useSeries";
import SeriesTable from "@/components/series/SeriesTable";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import { Kbd } from "@/components/ui/kbd";

export default function SeriesListPage() {
  const { data: series = [], isLoading, error } = useSeries();

  if (error) {
    return (
      <div className="p-8">
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
      {/* Page header */}
      <div className="px-5 py-3.5 border-b border-border flex items-center gap-3">
        <div>
          <div className="text-[18px] font-semibold tracking-tight leading-none">
            Library
          </div>
          <div className="font-mono text-[11px] text-muted-foreground mt-1.5">
            {isLoading
              ? "loading…"
              : total === 0
                ? "0 series"
                : `${total} series · ${comicCount} comic${comicCount === 1 ? "" : "s"} · ${mangaCount} manga`}
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <div
            className="hidden sm:flex items-center gap-2 px-2.5 py-1.5 rounded-[5px] border bg-card text-[12px] text-muted-foreground w-[220px]"
            style={{ borderColor: "var(--border)" }}
          >
            <SearchIcon className="w-3 h-3 shrink-0" />
            <span className="truncate">Filter series…</span>
            <Kbd className="ml-auto">/</Kbd>
          </div>

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
        </div>
      </div>

      {/* Table body */}
      <div className="flex-1 min-h-0 overflow-auto">
        <div className="px-5 py-4">
          <SeriesTable data={series} isLoading={isLoading} />
        </div>
      </div>
    </div>
  );
}
