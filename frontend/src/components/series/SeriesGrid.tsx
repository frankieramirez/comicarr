import type { Row } from "@tanstack/react-table";
import SeriesCard from "./SeriesCard";
import type { Comic } from "@/types";

interface SeriesGridProps {
  rows: Row<Comic>[];
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
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
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
