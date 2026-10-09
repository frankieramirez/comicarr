import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

/**
 * The one pagination rail for every table in the app.
 *
 * It reads as the bottom counterpart of the omni status bar: same card
 * surface, same hairline, same lowercase mono voice. Position on the left,
 * movement on the right. Client-paginated tables pass the numbers directly;
 * server-paginated ones go through `DataTableServerPagination`, which is a
 * thin adapter over this.
 */
interface DataTableFooterProps {
  /** 1-based index of the first row on this page. */
  start: number;
  /** 1-based index of the last row on this page. */
  end: number;
  /** Rows in the whole (filtered) set, not just this page. */
  total: number;
  /** 1-based page number. */
  page: number;
  /** Total pages. The pager is hidden when there is only one. */
  pageCount: number;
  onPrevPage: () => void;
  onNextPage: () => void;
  /** Extra state for the left rail, e.g. `3 selected`. */
  notes?: ReactNode;
}

const PAGE_BUTTON =
  "inline-flex items-center gap-1 rounded-control border border-border px-2 py-1 transition-colors hover:text-foreground hover:border-muted-foreground/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40";

export function DataTableFooter({
  start,
  end,
  total,
  page,
  pageCount,
  onPrevPage,
  onNextPage,
  notes,
}: DataTableFooterProps) {
  return (
    <div className="shrink-0 flex items-center gap-2 border-t border-border bg-card px-5 py-1.5 font-mono text-[11px] text-muted-foreground">
      <span className="tabular-nums">
        {total === 0 ? "no rows" : `${start}–${end} of ${total}`}
      </span>
      {notes != null && (
        <>
          <span aria-hidden="true" className="text-muted-foreground/40">
            ·
          </span>
          <span>{notes}</span>
        </>
      )}
      {pageCount > 1 && (
        <nav
          aria-label="Pagination"
          className="ml-auto flex items-center gap-2"
        >
          <button
            type="button"
            aria-label="Previous page"
            className={PAGE_BUTTON}
            onClick={onPrevPage}
            disabled={page <= 1}
          >
            <ChevronLeft className="w-3 h-3" aria-hidden="true" />
            prev
          </button>
          <span className="px-1 tabular-nums">
            page {page} of {pageCount}
          </span>
          <button
            type="button"
            aria-label="Next page"
            className={PAGE_BUTTON}
            onClick={onNextPage}
            disabled={page >= pageCount}
          >
            next
            <ChevronRight className="w-3 h-3" aria-hidden="true" />
          </button>
        </nav>
      )}
    </div>
  );
}
