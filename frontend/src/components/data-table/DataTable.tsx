import type { ReactNode } from "react";
import {
  flexRender,
  type Row,
  type Table as TanstackTable,
} from "@tanstack/react-table";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

interface DataTableProps<TData> {
  table: TanstackTable<TData>;
  onRowClick?: (row: TData) => void;
  renderSubRow?: (row: Row<TData>, colSpan: number) => ReactNode;
  className?: string;
}

export function DataTable<TData>({
  table,
  onRowClick,
  renderSubRow,
  className,
}: DataTableProps<TData>) {
  return (
    <div className={cn("min-w-0", className)}>
      <Table>
        <TableHeader className="bg-muted/30">
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow
              key={headerGroup.id}
              className="border-b border-border hover:bg-transparent"
            >
              {headerGroup.headers.map((header) => (
                <TableHead
                  key={header.id}
                  className="px-5 py-2 font-mono text-[10px] font-normal text-muted-foreground/70 uppercase tracking-wider"
                  style={
                    header.column.getSize() !== 150
                      ? { width: header.column.getSize() }
                      : undefined
                  }
                >
                  {header.isPlaceholder
                    ? null
                    : flexRender(
                        header.column.columnDef.header,
                        header.getContext(),
                      )}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.length ? (
            table.getRowModel().rows.map((row) => {
              const colSpan = table.getAllColumns().length;
              return (
                <>
                  <TableRow
                    key={row.id}
                    data-state={row.getIsSelected() && "selected"}
                    className={cn(
                      "border-b border-border/50",
                      onRowClick && "cursor-pointer",
                    )}
                    onClick={
                      onRowClick ? () => onRowClick(row.original) : undefined
                    }
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id} className="px-5 py-2">
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext(),
                        )}
                      </TableCell>
                    ))}
                  </TableRow>
                  {renderSubRow &&
                    row.getIsExpanded() &&
                    renderSubRow(row, colSpan)}
                </>
              );
            })
          ) : (
            <TableRow>
              <TableCell
                colSpan={table.getAllColumns().length}
                className="h-24 text-center text-muted-foreground"
              >
                No results.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
