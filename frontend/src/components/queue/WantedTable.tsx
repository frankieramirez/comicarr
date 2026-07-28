import { useNavigate } from "react-router-dom";
import type { Table as TanstackTable } from "@tanstack/react-table";
import EmptyState from "@/components/ui/EmptyState";
import { DataTable } from "@/components/data-table/DataTable";
import { DataTableServerPagination } from "@/components/data-table/DataTableServerPagination";
import type { WantedIssue, PaginationMeta } from "@/types";

interface WantedTableProps {
  /**
   * Built by `WantedPage` with `useTableState` (#395). The page owns the table
   * instance because it owns selection — `BulkActionBar` is its sibling — and
   * this component only renders it.
   */
  table: TanstackTable<WantedIssue>;
  pagination?: PaginationMeta;
  onNextPage?: () => void;
  onPrevPage?: () => void;
}

export default function WantedTable({
  table,
  pagination,
  onNextPage,
  onPrevPage,
}: WantedTableProps) {
  const navigate = useNavigate();

  if (table.getCoreRowModel().rows.length === 0) {
    return <EmptyState variant="wanted" />;
  }

  return (
    <div>
      <DataTable
        table={table}
        onRowClick={(row) => navigate(`/library/${row.ComicID}`)}
      />
      {pagination && onNextPage && onPrevPage && (
        <DataTableServerPagination
          pagination={pagination}
          onNextPage={onNextPage}
          onPrevPage={onPrevPage}
        />
      )}
    </div>
  );
}
