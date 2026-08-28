import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  columnFilteringFeature,
  columnSizingFeature,
  columnVisibilityFeature,
  createExpandedRowModel,
  createFilteredRowModel,
  createPaginatedRowModel,
  createSortedRowModel,
  globalFilteringFeature,
  rowExpandingFeature,
  rowPaginationFeature,
  rowSelectionFeature,
  rowSortingFeature,
  sortFn_alphanumeric,
  sortFn_datetime,
  sortFn_text,
  tableFeatures,
  useTable,
  type ExpandedState,
  type ReactTable,
  type Row,
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
 * This is not a hook that sits beside `useTable` — it *wraps* it, and an
 * ESLint rule makes it the only file allowed to import `useTable`. That is
 * what lets `getRowId` be required rather than merely offered: a hook beside
 * the call can only suggest a correct row id, and TanStack's index-based
 * default is precisely the silent default nobody chose (#307, #359).
 *
 * Every state slice and `on*Change` handler is `Omit`ted from the passthrough,
 * so a caller cannot quietly take one back. That is deliberate cost: `expanded`
 * is owned here because the omission dragged it in, not because it earned a
 * place (#359).
 */

export type SelectAllScope = "filtered" | "page";

/**
 * The native v9 feature set shared by every Comicarr table. Keeping this
 * static gives column helpers and table props one feature type while allowing
 * TanStack to tree-shake features Comicarr does not use.
 */
export const comicarrTableFeatures = tableFeatures({
  columnFilteringFeature,
  globalFilteringFeature,
  rowSortingFeature,
  rowPaginationFeature,
  rowExpandingFeature,
  rowSelectionFeature,
  columnSizingFeature,
  columnVisibilityFeature,
  filteredRowModel: createFilteredRowModel(),
  sortedRowModel: createSortedRowModel(),
  paginatedRowModel: createPaginatedRowModel(),
  expandedRowModel: createExpandedRowModel(),
  sortFns: {
    alphanumeric: sortFn_alphanumeric,
    datetime: sortFn_datetime,
    text: sortFn_text,
  },
});

export type ComicarrTableFeatures = typeof comicarrTableFeatures;
export type ComicarrTable<TData extends RowData> = ReactTable<
  ComicarrTableFeatures,
  TData
>;
export type ComicarrCoreTable<TData extends RowData> = Table<
  ComicarrTableFeatures,
  TData
>;
export type ComicarrRow<TData extends RowData> = Row<
  ComicarrTableFeatures,
  TData
>;

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
  | "features"
  | "manualPagination"
  | "autoResetPageIndex"
  | "enableRowSelection";

export type UseTableStateOptions<TData extends RowData> = Omit<
  TableOptions<ComicarrTableFeatures, TData>,
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

export type UseTableStateResult<TData extends RowData> = {
  table: ComicarrTable<TData>;
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
export function getIsAllSelected<TData extends RowData>(
  table: ComicarrCoreTable<TData>,
): boolean | "indeterminate" {
  const isPageScope = table.options.meta?.selectAllScope === "page";
  const isAll = isPageScope
    ? table.getIsAllPageRowsSelected()
    : table.getIsAllRowsSelected();
  const isSome = isPageScope
    ? table.getIsSomePageRowsSelected()
    : table.getIsSomeRowsSelected();

  return isAll || (isSome && "indeterminate");
}

export function toggleAllSelected<TData extends RowData>(
  table: ComicarrCoreTable<TData>,
  value: boolean,
): void {
  if (table.options.meta?.selectAllScope === "page") {
    table.toggleAllPageRowsSelected(value);
    return;
  }
  table.toggleAllRowsSelected(value);
}

export function useTableState<TData extends RowData>({
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

  const seenRows = useRef(false);
  const rowCount = passthrough.data.length;
  useEffect(() => {
    if (rowCount > 0) seenRows.current = true;
  });
  // eslint-disable-next-line react-hooks/refs
  const autoResetPageIndex = seenRows.current;

  const table = useTable({
    ...passthrough,
    features: comicarrTableFeatures,
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
          autoResetPageIndex,
        }
      : { manualPagination: true }),
    enableRowSelection: selection !== undefined,
  });

  const pageSize = pagination?.pageSize;
  const previousPageSize = useRef(pageSize);
  useLayoutEffect(() => {
    if (previousPageSize.current !== pageSize) {
      previousPageSize.current = pageSize;
      if (store) {
        store.setState({ pageIndex: 0 });
      } else {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setLocalPageIndex(0);
      }
    }
  }, [pageSize, store]);

  const filteredRows = table.getFilteredRowModel().rows;
  const visibleRowIds = useMemo(
    () => new Set(filteredRows.map((row) => row.id)),
    [filteredRows],
  );

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
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
