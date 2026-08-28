import { DataTableFooter } from "@/components/data-table/DataTableFooter";
import type { PaginationMeta } from "@/types";

interface DataTableServerPaginationProps {
  pagination: PaginationMeta;
  onNextPage: () => void;
  onPrevPage: () => void;
}

/**
 * Adapter: turns an API `pagination` block into the shared table footer, so a
 * server-paginated table reads exactly like a client-paginated one.
 */
export function DataTableServerPagination({
  pagination,
  onNextPage,
  onPrevPage,
}: DataTableServerPaginationProps) {
  const { total, offset } = pagination;
  const limit = pagination.limit || 1;
  const returned = pagination.returned ?? Math.min(limit, total - offset);

  return (
    <DataTableFooter
      start={total === 0 ? 0 : offset + 1}
      end={offset + Math.max(0, returned)}
      total={total}
      page={Math.floor(offset / limit) + 1}
      pageCount={Math.max(1, Math.ceil(total / limit))}
      onPrevPage={onPrevPage}
      onNextPage={onNextPage}
    />
  );
}
