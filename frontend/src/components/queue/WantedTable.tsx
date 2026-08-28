import { useNavigate } from "react-router-dom";
import EmptyState from "@/components/ui/EmptyState";
import { DataTable } from "@/components/data-table/DataTable";
import { DataTableServerPagination } from "@/components/data-table/DataTableServerPagination";
import type { ComicarrTable } from "@/components/data-table/useTableState";
import type { WantedIssue, PaginationMeta } from "@/types";

interface WantedTableProps {
  /**
   * Built by `WantedPage` with `useTableState` (#395). The page owns the table
   * instance because it owns selection — `BulkActionBar` is its sibling — and
   * this component only renders it.
   */
  table: ComicarrTable<WantedIssue>;
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
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex-1 min-h-0 overflow-auto">
        <DataTable
          table={table}
          onRowClick={(row) => navigate(`/library/${row.ComicID}`)}
        />
      </div>
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
