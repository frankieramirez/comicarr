import type { Column } from "@tanstack/react-table";
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";

interface DataTableSortHeaderProps<TData> {
  column: Column<TData>;
  title: string;
}

export function DataTableSortHeader<TData>({
  column,
  title,
}: DataTableSortHeaderProps<TData>) {
  if (!column.getCanSort()) {
    return <span>{title}</span>;
  }

  return (
    <div
      className="flex items-center gap-1 cursor-pointer select-none hover:text-foreground"
      role="button"
      tabIndex={0}
      onClick={column.getToggleSortingHandler()}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          column.toggleSorting();
        }
      }}
    >
      <span>{title}</span>
      {column.getIsSorted() === "asc" ? (
        <ChevronUp className="w-4 h-4" />
      ) : column.getIsSorted() === "desc" ? (
        <ChevronDown className="w-4 h-4" />
      ) : (
        <ChevronsUpDown className="w-4 h-4 text-muted-foreground/50" />
      )}
    </div>
  );
}
