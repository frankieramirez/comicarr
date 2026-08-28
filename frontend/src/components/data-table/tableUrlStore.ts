import { useMemo } from "react";
import {
  createParser,
  parseAsInteger,
  parseAsString,
  throttle,
  useQueryStates,
  type Options,
} from "nuqs";
import type { SortingState } from "@tanstack/react-table";
import { SORT_DELIMITER } from "@/lib/delimiters";
import type { TableStore } from "./useTableState";

/**
 * The caller-side half of #377's decision: `useTableState` takes a `store`
 * adapter but never opens one and never imports nuqs. Seven of the eight
 * pre-hook instances held this state in plain React state, so a hook-owned
 * store would have handed URL state to tables that never had it.
 *
 * Everything here is nuqs-aware and lives on the caller's side of that line.
 * `useTableState.ts` imports nothing from this file.
 */

/**
 * `eq` is added here rather than at the first `withDefault`, and that timing is
 * the whole point: exporting a shared parser is what arms the bug. Without
 * `eq`, nuqs cannot tell a value from the parser's default, so the moment any
 * caller declares a default sort it gets serialised into every URL instead of
 * being omitted (#377).
 */
export const sortParser = createParser({
  parse(value: string) {
    const [id, direction] = value.split(SORT_DELIMITER);
    if (!id) return null;
    return { id, desc: direction === "desc" };
  },
  serialize(value: { id: string; desc: boolean }) {
    return `${value.id}${SORT_DELIMITER}${value.desc ? "desc" : "asc"}`;
  },
  eq(a: { id: string; desc: boolean }, b: { id: string; desc: boolean }) {
    return a.id === b.id && a.desc === b.desc;
  },
});

/**
 * The three URL-worthy slices as a fragment, so a caller can spread it into a
 * wider `useQueryStates` map alongside its own domain filters. `search` folds
 * into this one map — the key name is unchanged, so existing bookmarks survive
 * — and carries a per-parser rate limit rather than the deprecated
 * `throttleMs`, a capability #368 confirmed became real in nuqs 2.9.1.
 *
 * Batching the page reset at the same 300ms is strictly better than the two
 * writes it replaces, which left a 300ms window where the URL read
 * *old search, page 0* (#377).
 */
/**
 * The URL is user-supplied, and `?page=-1` parses cleanly to -1, which would
 * reach TanStack as a negative `pageIndex`. Floored at the parser so the store
 * cannot expose one.
 *
 * Out-of-range *high* pages are deliberately left alone: clamping those is the
 * render-time, display-only concern #360 assigned to the caller, and the
 * rewrite that tries to tell "rows have not arrived" from "genuinely out of
 * range" *is* the bug #381 fixed.
 */
const pageParser = createParser({
  parse(value: string) {
    const page = parseAsInteger.parse(value);
    return page === null ? null : Math.max(0, page);
  },
  serialize(value: number) {
    return String(Math.max(0, value));
  },
});

export const tableUrlParams = {
  page: pageParser.withDefault(0),
  sort: sortParser,
  search: parseAsString.withDefault("").withOptions({
    limitUrlUpdates: throttle(300),
  }),
};

/**
 * Adapts the params above to the shape `useTableState` consumes. All-or-nothing
 * by design: a table wanting mixed backends composes them inside its own
 * adapter, because the hook's contract is that it has *one* store, not that it
 * knows what is behind it.
 */
export function useTableUrlStore(
  options?: Pick<Options, "history" | "shallow" | "scroll">,
): TableStore {
  const [params, setParams] = useQueryStates(tableUrlParams, options);

  const sortId = params.sort?.id;
  const sortDesc = params.sort?.desc;
  const sorting = useMemo<SortingState>(
    () => (sortId ? [{ id: sortId, desc: sortDesc ?? false }] : []),
    [sortId, sortDesc],
  );

  const { page, search } = params;

  return useMemo(
    () => ({
      state: { sorting, globalFilter: search, pageIndex: page },
      setState: (patch) => {
        void setParams({
          ...("sorting" in patch
            ? { sort: patch.sorting?.length ? patch.sorting[0] : null }
            : {}),
          ...("globalFilter" in patch ? { search: patch.globalFilter } : {}),
          ...("pageIndex" in patch
            ? { page: patch.pageIndex === 0 ? null : patch.pageIndex }
            : {}),
        });
      },
    }),
    [sorting, search, page, setParams],
  );
}
