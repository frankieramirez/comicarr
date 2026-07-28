import { useCallback, useMemo, useState } from "react";

/**
 * The page for tables that paginate outside TanStack — server offset/limit.
 *
 * `useTableState` structurally cannot own this: the page is an *input* to the
 * fetch that produces the `data` the hook consumes, so hook-ownership would be
 * circular. Hence #360's rule that the absence of `pagination` is itself a
 * model, and hence this hook being called *before* the query rather than after.
 *
 * It collapses four duplicated `useState(0)` sites — `ActivityPage` twice,
 * `WantedPage`, `ImportPage` — together with their copied next/prev handlers.
 * (#360 records five; the fifth was `UpcomingTable`, which is unpaginated and
 * holds no page state at all.)
 *
 * `resetPage` is explicit rather than automatic because TanStack's
 * `autoResetPageIndex` is inert under `manualPagination` — for this model the
 * reset-on-sort-or-filter invariant has no owner but the caller.
 */
export function useServerPage(pageSize: number) {
  const [page, setPage] = useState(0);

  const nextPage = useCallback(() => setPage((current) => current + 1), []);
  const prevPage = useCallback(
    () => setPage((current) => Math.max(0, current - 1)),
    [],
  );
  const resetPage = useCallback(() => setPage(0), []);

  return useMemo(
    () => ({
      page,
      limit: pageSize,
      offset: page * pageSize,
      nextPage,
      prevPage,
      resetPage,
    }),
    [page, pageSize, nextPage, prevPage, resetPage],
  );
}
