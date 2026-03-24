import { Button } from "@/components/ui/button";
import type { PaginationMeta } from "@/types";

interface DataTableServerPaginationProps {
  pagination: PaginationMeta;
  onNextPage: () => void;
  onPrevPage: () => void;
}

export function DataTableServerPagination({
  pagination,
  onNextPage,
  onPrevPage,
}: DataTableServerPaginationProps) {
  const start = pagination.offset + 1;
  const end = Math.min(pagination.offset + pagination.limit, pagination.total);

  return (
    <div className="border-t border-card-border px-6 py-3 flex items-center justify-between bg-muted/50">
      <div className="text-sm text-muted-foreground">
        Showing {start} to {end} of {pagination.total}
      </div>
      <div className="flex items-center space-x-2">
        <Button
          variant="outline"
          size="sm"
          onClick={onPrevPage}
          disabled={pagination.offset === 0}
        >
          Previous
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={onNextPage}
          disabled={!pagination.has_more}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
