import type { CellData, Column, RowData } from "@tanstack/react-table";
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";
import type { ComicarrTableFeatures } from "@/components/data-table/useTableState";

interface DataTableSortHeaderProps<
  TData extends RowData,
  TValue extends CellData,
> {
  column: Column<ComicarrTableFeatures, TData, TValue>;
  title: string;
}

export function DataTableSortHeader<
  TData extends RowData,
  TValue extends CellData,
>({ column, title }: DataTableSortHeaderProps<TData, TValue>) {
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
        <ChevronUp className="w-4 h-4" aria-hidden />
      ) : column.getIsSorted() === "desc" ? (
        <ChevronDown className="w-4 h-4" aria-hidden />
      ) : (
        <ChevronsUpDown
          className="w-4 h-4 text-muted-foreground/50"
          aria-hidden
        />
      )}
    </div>
  );
}
