import SeriesCard from "./SeriesCard";
import type { ComicarrRow } from "@/components/data-table/useTableState";
import type { Comic } from "@/types";

interface SeriesGridProps {
  rows: ComicarrRow<Comic>[];
  onCardClick: (comic: Comic) => void;
}

export default function SeriesGrid({ rows, onCardClick }: SeriesGridProps) {
  if (rows.length === 0) {
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground">
        No results.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-7">
      {rows.map((row) => (
        <SeriesCard
          key={row.id}
          comic={row.original}
          onClick={() => onCardClick(row.original)}
        />
      ))}
    </div>
  );
}
