import { TooltipProvider } from "@/components/ui/tooltip";
import EmptyState from "@/components/ui/EmptyState";
import { DataTable } from "@/components/data-table/DataTable";
import { DataTableServerPagination } from "@/components/data-table/DataTableServerPagination";
import type { ComicarrTable } from "@/components/data-table/useTableState";
import type { ImportGroup, PaginationMeta } from "@/types";

interface ImportTableProps {
  /**
   * Built by `ImportPage` with `useTableState` (#396). The page owns the table
   * instance because it owns selection — `ImportBulkActions` is its sibling —
   * and this component only renders it.
   */
  table: ComicarrTable<ImportGroup>;
  pagination?: PaginationMeta;
  onNextPage?: () => void;
  onPrevPage?: () => void;
  /** Opens a group in the pick panel. */
  onOpenGroup?: (group: ImportGroup) => void;
  /** Row id of the group the pick panel shows. */
  openRowId?: string | null;
  emptyTitle?: string;
  emptyDescription?: string;
}

export default function ImportTable({
  table,
  pagination,
  onNextPage,
  onPrevPage,
  onOpenGroup,
  openRowId,
  emptyTitle = "No pending imports",
  emptyDescription = "All files have been imported or there are no files to import.",
}: ImportTableProps) {
  if (table.getCoreRowModel().rows.length === 0) {
    return (
      <EmptyState
        variant="search"
        title={emptyTitle}
        description={emptyDescription}
      />
    );
  }

  return (
    <TooltipProvider delayDuration={150}>
      <DataTable
        table={table}
        className="overflow-x-auto px-0"
        onRowClick={onOpenGroup}
        activeRowId={openRowId ?? undefined}
      />
      {pagination &&
        onNextPage &&
        onPrevPage &&
        pagination.total > pagination.limit && (
          <DataTableServerPagination
            pagination={pagination}
            onNextPage={onNextPage}
            onPrevPage={onPrevPage}
          />
        )}
    </TooltipProvider>
  );
}
