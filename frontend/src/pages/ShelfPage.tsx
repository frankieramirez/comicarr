import { plural, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Download } from "lucide-react";
import { useState } from "react";
import PageHeader from "@/components/layout/PageHeader";
import LibraryTabs from "@/components/series/LibraryTabs";
import {
  ShelfSheet,
  type ShelfSheetTarget,
} from "@/components/shelf/ShelfSheet";
import { buttonVariants } from "@/components/ui/button";
import EmptyState from "@/components/ui/EmptyState";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import { Input } from "@/components/ui/input";
import { useDebounce } from "@/hooks/use-debounce";
import { useLibrarySummary } from "@/hooks/useLibrarySummary";
import { useShelfCopies } from "@/hooks/useShelf";
import { formatCents } from "@/lib/shelf";
import type { ShelfCopy } from "@/types";

// The API's largest page. Past it, the search box narrows the list.
const PAGE = 500;
const GRID =
  "grid grid-cols-[minmax(0,1fr)_auto] md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_110px_minmax(0,1fr)_80px] items-center gap-3";

function sheetTarget(copy: ShelfCopy): ShelfSheetTarget {
  return {
    item: {
      ComicID: copy.ComicID,
      ItemID: copy.ItemID ?? undefined,
      VolumeNumber: copy.VolumeNumber ?? undefined,
    },
    title: [copy.SeriesName, copy.ItemLabel].filter(Boolean).join(" "),
  };
}

/** Every print copy on the shelf, across all series. */
export default function ShelfPage() {
  const summary = useLibrarySummary();
  const [search, setSearch] = useState("");
  const query = useDebounce(search.trim(), 250);
  const copies = useShelfCopies({ q: query, limit: PAGE });
  const [target, setTarget] = useState<ShelfSheetTarget | null>(null);
  const page = copies.data;
  const list = page?.results ?? [];
  const shown = list.length;
  const total = page?.total ?? 0;
  const paid = formatCents(page?.paid_cents ?? 0);

  return (
    <div className="page-transition flex h-full min-h-0 flex-col">
      <PageHeader
        title={t`Library`}
        meta={summary}
        actions={
          <a
            href="/api/shelf/export.csv"
            download
            className={buttonVariants({ variant: "outline", size: "toolbar" })}
          >
            <Download />
            <Trans>Export CSV</Trans>
          </a>
        }
      />
      <LibraryTabs />

      <div className="flex shrink-0 flex-wrap items-center gap-3 px-8 py-3">
        <Input
          type="search"
          value={search}
          aria-label={t`Search your shelf`}
          placeholder={t`Search series, variant, storage or notes`}
          className="h-8 max-w-sm"
          onChange={(event) => setSearch(event.target.value)}
        />
        {page ? (
          <div className="mono-meta ms-auto" data-testid="shelf-totals">
            {plural(total, { one: "# copy", other: "# copies" })}
            {page.paid_cents > 0 ? ` · ${t`${paid} paid`}` : null}
          </div>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-auto pb-6">
        {copies.error ? (
          <div className="px-8">
            <ErrorDisplay
              error={copies.error}
              title={t`Unable to load your shelf`}
              onRetry={() => void copies.refetch()}
              isRetrying={copies.isFetching}
            />
          </div>
        ) : page && list.length === 0 ? (
          <EmptyState
            variant="custom"
            title={
              query ? t`Nothing on your shelf matches` : t`Your shelf is empty`
            }
            description={
              query
                ? undefined
                : t`Open a series and use the shelf mark on an issue or volume to record a print copy.`
            }
          />
        ) : (
          <>
            <div
              className={`${GRID} sticky top-0 z-10 mx-8 h-8 border-b border-border-subtle bg-background px-2 text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground`}
            >
              <div>
                <Trans>Book</Trans>
              </div>
              <div className="max-md:hidden">
                <Trans>Variant</Trans>
              </div>
              <div className="max-md:hidden">
                <Trans>Grade</Trans>
              </div>
              <div className="max-md:hidden">
                <Trans>Storage</Trans>
              </div>
              <div className="text-end">
                <Trans>Paid</Trans>
              </div>
            </div>
            {list.map((copy) => (
              <button
                key={copy.CopyID}
                type="button"
                data-testid="shelf-row"
                onClick={() => setTarget(sheetTarget(copy))}
                className={`${GRID} mx-8 min-h-9 w-[calc(100%-4rem)] border-b border-border-subtle px-2 py-1 text-start text-[13px] transition-colors hover:bg-surface-1`}
              >
                <div className="min-w-0 truncate">
                  {copy.SeriesName}{" "}
                  <span className="text-muted-foreground">
                    {copy.ItemLabel}
                  </span>
                </div>
                <div className="min-w-0 truncate text-foreground-2 max-md:hidden">
                  {copy.VariantName ?? "—"}
                </div>
                <div className="min-w-0 truncate text-foreground-2 max-md:hidden">
                  {copy.Grade ?? "—"}
                </div>
                <div className="min-w-0 truncate text-foreground-2 max-md:hidden">
                  {copy.Storage ?? "—"}
                </div>
                <div className="text-end font-mono text-[12px]">
                  {copy.PaidCents === null ? "—" : formatCents(copy.PaidCents)}
                </div>
              </button>
            ))}
            {total > shown ? (
              <p className="mx-8 px-2 py-3 text-[12px] text-muted-foreground">
                {t`Showing the newest ${shown} of ${total}. Search to narrow the list.`}
              </p>
            ) : null}
          </>
        )}
      </div>

      <ShelfSheet target={target} onClose={() => setTarget(null)} />
    </div>
  );
}
