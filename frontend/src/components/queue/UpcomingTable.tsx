import type { Table as TanstackTable } from "@tanstack/react-table";
import { DataTable } from "@/components/data-table/DataTable";
import type { UpcomingIssue } from "@/types";

interface UpcomingTableProps {
  /**
   * Built by `ReleasesPage`'s `MyReleasesView` with `useTableState` (#395).
   * The page owns the table instance because it owns selection —
   * `BulkActionBar` is its sibling — and this component only renders it.
   */
  table: TanstackTable<UpcomingIssue>;
}

export default function UpcomingTable({ table }: UpcomingTableProps) {
  if (table.getCoreRowModel().rows.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        No upcoming releases this week.
      </div>
    );
  }

  return <DataTable table={table} />;
}
