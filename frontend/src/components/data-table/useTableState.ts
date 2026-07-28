import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getCoreRowModel,
  getExpandedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ExpandedState,
  type RowData,
  type RowSelectionState,
  type SortingState,
  type Table,
  type TableOptions,
  type Updater,
} from "@tanstack/react-table";

/**
 * The single owner of TanStack table state.
 *
 * This is not a hook that sits beside `useReactTable` — it *wraps* it, and an
 * ESLint rule makes it the only file allowed to import `useReactTable`. That is
 * what lets `getRowId` be required rather than merely offered: a hook beside
 * the call can only suggest a correct row id, and TanStack's index-based
 * default is precisely the silent default nobody chose (#307, #359).
 *
 * Every state slice and `on*Change` handler is `Omit`ted from the passthrough,
 * so a caller cannot quietly take one back. That is deliberate cost: `expanded`
 * is owned here because the omission dragged it in, not because it earned a
 * place (#359).
 */

declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface TableMeta<TData extends RowData> {
    /**
     * Set by `useTableState` from `selection.scope`, so a header checkbox can
     * honour the table's scope without the column closing over the hook's
     * return value (columns are memoised; the `table` argument is not).
     */
    selectAllScope?: SelectAllScope;
  }
}

export type SelectAllScope = "filtered" | "page";

/**
 * The three slices worth putting in a URL. The caller supplies the backing
 * store; the hook never opens one and never imports nuqs (#377).
 */
export type TableStoreState = {
  sorting: SortingState;
  globalFilter: string;
  pageIndex: number;
};

export type TableStore = {
  state: TableStoreState;
  /**
   * Patch semantics: only the named slices change. One call per hook update —
   * the hook never writes two slices at once, because #360 removed the
   * hand-rolled page reset that would have needed it.
   */
  setState: (patch: Partial<TableStoreState>) => void;
};

/**
 * State slices and handlers the hook owns outright. Passing any of these is a
 * type error rather than a silently ignored option.
 */
type OwnedOptions =
  | "state"
  | "initialState"
  | "getRowId"
  | "onSortingChange"
  | "onGlobalFilterChange"
  | "onRowSelectionChange"
  | "onPaginationChange"
  | "onExpandedChange"
  | "getCoreRowModel"
  | "getSortedRowModel"
  | "getFilteredRowModel"
  | "getPaginationRowModel"
  | "getExpandedRowModel"
  | "manualPagination"
  | "autoResetPageIndex"
  // Derived from `selection` and set after the passthrough spread, so a caller
  // passing it would be silently overridden — precisely the quiet no-op the
  // Omit exists to make impossible.
  | "enableRowSelection";

export type UseTableStateOptions<TData> = Omit<
  TableOptions<TData>,
  OwnedOptions
> & {
  /**
   * Required and non-defaultable, narrowed to drop TanStack's `index`
   * parameter. `(row, index) => …` stops compiling, which is the point:
   * a positional row id cannot survive a data change (#355, #359).
   */
  getRowId: (row: TData) => string;
  /**
   * Absence is a model: without it the table paginates outside TanStack
   * (server offset/limit), gets `manualPagination`, and holds no page state
   * here — the page is an input to the fetch that produces `data`, so owning
   * it would be circular (#360).
   */
  pagination?: { pageSize: number };
  /**
   * Absence means the table has no row selection at all. When present, `scope`
   * is required with no default — scope is semantics, not identity, so it must
   * be named (#359, #382).
   */
  selection?: { scope: SelectAllScope };
  /** All-or-nothing URL adapter over the three slices above (#377). */
  store?: TableStore;
  /** Only consulted when no `store` is injected. */
  initialSorting?: SortingState;
};

export type UseTableStateResult<TData> = {
  table: Table<TData>;
  /**
   * Always derived from `getSelectedRowModel()`, never from raw
   * `state.rowSelection` keys — the raw object is what exposes ids whose rows
   * have gone, and it is what every pre-hook decoder read (#355, #365).
   */
  selectedRows: TData[];
  selectedIds: string[];
  /** Backed by `resetRowSelection(true)`, which also clears out-of-scope ids. */
  clearSelection: () => void;
};

function applyUpdater<T>(updater: Updater<T>, current: T): T {
  return typeof updater === "function"
    ? (updater as (old: T) => T)(current)
    : updater;
}

/**
 * Header-checkbox helpers that honour the table's `selectAllScope`. Columns
 * call these instead of picking a TanStack pair themselves, so the scope is
 * decided once, where it was named.
 */
export function getIsAllSelected<TData>(
  table: Table<TData>,
): boolean | "indeterminate" {
  // Both halves have to read the same scope. Mixing them — an all-check scoped
  // to the page and a some-check scoped to everything — renders a page with no
  // selected rows as indeterminate whenever any *other* page holds a selection.
  const isPageScope = table.options.meta?.selectAllScope === "page";
  const isAll = isPageScope
    ? table.getIsAllPageRowsSelected()
    : table.getIsAllRowsSelected();
  const isSome = isPageScope
    ? table.getIsSomePageRowsSelected()
    : table.getIsSomeRowsSelected();

  return isAll || (isSome && "indeterminate");
}

export function toggleAllSelected<TData>(
  table: Table<TData>,
  value: boolean,
): void {
  if (table.options.meta?.selectAllScope === "page") {
    table.toggleAllPageRowsSelected(value);
    return;
  }
  table.toggleAllRowsSelected(value);
}

export function useTableState<TData>({
  getRowId,
  pagination,
  selection,
  store,
  initialSorting,
  meta,
  ...passthrough
}: UseTableStateOptions<TData>): UseTableStateResult<TData> {
  const [localSorting, setLocalSorting] = useState<SortingState>(
    initialSorting ?? [],
  );
  const [localGlobalFilter, setLocalGlobalFilter] = useState("");
  const [localPageIndex, setLocalPageIndex] = useState(0);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [expanded, setExpanded] = useState<ExpandedState>({});

  const sorting = store ? store.state.sorting : localSorting;
  const globalFilter = store ? store.state.globalFilter : localGlobalFilter;
  const pageIndex = store ? store.state.pageIndex : localPageIndex;

  const setSorting = useCallback(
    (updater: Updater<SortingState>) => {
      const next = applyUpdater(updater, sorting);
      if (store) store.setState({ sorting: next });
      else setLocalSorting(next);
    },
    [sorting, store],
  );

  const setGlobalFilter = useCallback(
    (updater: Updater<string>) => {
      const next = applyUpdater(updater, globalFilter);
      if (store) store.setState({ globalFilter: next });
      else setLocalGlobalFilter(next);
    },
    [globalFilter, store],
  );

  const paginationState = useMemo(
    () =>
      pagination
        ? { pageIndex, pageSize: pagination.pageSize }
        : { pageIndex: 0, pageSize: 0 },
    [pageIndex, pagination],
  );

  const setPagination = useCallback(
    (updater: Updater<{ pageIndex: number; pageSize: number }>) => {
      const next = applyUpdater(updater, paginationState);
      if (next.pageIndex === paginationState.pageIndex) return;
      if (store) store.setState({ pageIndex: next.pageIndex });
      else setLocalPageIndex(next.pageIndex);
    },
    [paginationState, store],
  );

  // Auto-reset is armed one render AFTER rows first arrive. TanStack reads this
  // option synchronously inside `_autoResetPageIndex`, before it queues the
  // reset onto a microtask, so a ref read at render time is the value that
  // decides. Arming it immediately would let the reset fire against a page a
  // render-time clamp had already raised, stripping a deep link (#372, #381).
  const seenRows = useRef(false);
  const rowCount = passthrough.data.length;
  useEffect(() => {
    if (rowCount > 0) seenRows.current = true;
  });

  const table = useReactTable({
    ...passthrough,
    meta: { ...meta, selectAllScope: selection?.scope },
    getRowId,
    state: {
      sorting,
      globalFilter,
      rowSelection,
      expanded,
      ...(pagination ? { pagination: paginationState } : {}),
    },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    onRowSelectionChange: setRowSelection,
    onExpandedChange: setExpanded,
    ...(pagination
      ? {
          onPaginationChange: setPagination,
          getPaginationRowModel: getPaginationRowModel(),
          autoResetPageIndex: seenRows.current,
        }
      : { manualPagination: true }),
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    enableRowSelection: selection !== undefined,
  });

  // A page-size change alters no `data` identity, so TanStack's auto-reset
  // provably cannot see it — the one page reset the hook still owes (#360).
  const pageSize = pagination?.pageSize;
  const previousPageSize = useRef(pageSize);
  useEffect(() => {
    if (previousPageSize.current !== pageSize) {
      previousPageSize.current = pageSize;
      if (store) store.setState({ pageIndex: 0 });
      else setLocalPageIndex(0);
    }
  }, [pageSize, store]);

  // TanStack never prunes stale selection ids and offers no option to — it is
  // documented as intentional (#355). Rows leave for reasons the hook cannot
  // see (a refetch, a domain filter applied before `data` arrives here), which
  // is exactly why pruning is generic: it drops ids whose rows are gone without
  // knowing why they went. Deriving outputs from `getSelectedRowModel()` is not
  // a substitute, because the header checkbox counts raw state (#359).
  // Read the row models during render rather than memoising on `table`: the
  // table instance is referentially stable for the life of the component, so
  // `[table]` would compute this once and pruning would never fire again. The
  // row-model getters are memoised inside TanStack on the state they derive
  // from, so their `rows` arrays are the honest dependency.
  const filteredRows = table.getFilteredRowModel().rows;
  const visibleRowIds = useMemo(
    () => new Set(filteredRows.map((row) => row.id)),
    [filteredRows],
  );

  useEffect(() => {
    setRowSelection((current) => {
      const selectedKeys = Object.keys(current);
      if (selectedKeys.length === 0) return current;

      const survivors: RowSelectionState = {};
      let dropped = false;
      for (const key of selectedKeys) {
        if (visibleRowIds.has(key)) survivors[key] = current[key];
        else dropped = true;
      }

      return dropped ? survivors : current;
    });
  }, [visibleRowIds]);

  const selectedRows = table.getSelectedRowModel().rows;

  const clearSelection = useCallback(() => {
    // Existing *because* v8's deselect-all is scope-limited: under page scope
    // `toggleAllSelected(table, false)` clears the page and leaves every other
    // selected id behind, with no escape hatch (#355). Clearing has to be a
    // separate operation from deselect-all, not an argument to it.
    //
    // The `true` is explicit rather than load-bearing — it resets to `{}`
    // instead of `initialState.rowSelection`, and `initialState` is `Omit`ted
    // so no caller can set one. It is kept so the intent survives if that
    // changes.
    table.resetRowSelection(true);
  }, [table]);

  return {
    table,
    selectedRows: useMemo(
      () => selectedRows.map((row) => row.original),
      [selectedRows],
    ),
    selectedIds: useMemo(
      () => selectedRows.map((row) => row.id),
      [selectedRows],
    ),
    clearSelection,
  };
}
