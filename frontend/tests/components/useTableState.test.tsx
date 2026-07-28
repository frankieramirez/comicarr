import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { createColumnHelper } from "@tanstack/react-table";
import {
  getIsAllSelected,
  toggleAllSelected,
  useTableState,
  type TableStore,
} from "@/components/data-table/useTableState";
import { encodeRowId } from "@/components/data-table/rowId";

/**
 * The hook layer of #365's split: everything here is identical for every caller
 * and independent of rendering — pruning, select-all scope, clearSelection, the
 * store adapter, auto-reset arming. It is written once and deliberately NOT
 * re-tested per call site.
 *
 * Five of these carry a #307 reference. They are the generic half of
 * `QueueTableSelection.test.tsx`, which asserts the same invariants through
 * two components; those move here as each site migrates (#395), and per #365 no
 * pin retires unless its replacement lands in the same PR. Until then both
 * exist, which is intentional overlap rather than duplication.
 *
 * `renderHook` appears nowhere else in this repo — a new idiom adopted
 * deliberately, because six-way duplication of generic behaviour is worse.
 */

type Row = { id: string; name: string; group: string };

const columnHelper = createColumnHelper<Row>();
const columns = [
  columnHelper.accessor("name", { id: "name" }),
  columnHelper.accessor("group", { id: "group" }),
];

function rows(...ids: string[]): Row[] {
  return ids.map((id) => ({ id, name: `row ${id}`, group: "a" }));
}

function renderTable(initial: {
  data: Row[];
  pageSize?: number;
  scope?: "filtered" | "page";
  store?: TableStore;
}) {
  return renderHook(
    ({ data, pageSize, scope, store }: typeof initial) =>
      useTableState<Row>({
        data,
        columns,
        getRowId: (row) => row.id,
        selection: scope ? { scope } : undefined,
        pagination: pageSize ? { pageSize } : undefined,
        store,
      }),
    { initialProps: initial },
  );
}

describe("useTableState", () => {
  describe("selection identity (#307)", () => {
    it("reports ids, not row positions, for a non-adjacent multi-row selection", () => {
      const { result } = renderTable({
        data: rows("a", "b", "c", "d"),
        scope: "filtered",
      });

      act(() => {
        result.current.table.getRowModel().rows[0].toggleSelected(true);
        result.current.table.getRowModel().rows[2].toggleSelected(true);
      });

      expect(result.current.selectedIds).toEqual(["a", "c"]);
      expect(result.current.selectedRows.map((row) => row.name)).toEqual([
        "row a",
        "row c",
      ]);
    });

    it("drops selected ids whose rows are no longer present (#307)", () => {
      const { result, rerender } = renderTable({
        data: rows("a", "b", "c"),
        scope: "filtered",
      });

      act(() => {
        result.current.table.getRowModel().rows[1].toggleSelected(true);
      });
      expect(result.current.selectedIds).toEqual(["b"]);

      // The row leaves for a reason the hook cannot see — a refetch, a domain
      // filter applied before `data` reaches it. Pruning is generic precisely
      // so it does not need to know which.
      rerender({ data: rows("a", "c"), scope: "filtered" });

      expect(result.current.selectedIds).toEqual([]);
      expect(Object.keys(result.current.table.getState().rowSelection)).toEqual(
        [],
      );
    });

    it("prunes raw state, not just the derived output, so the header checkbox agrees (#307)", () => {
      const { result, rerender } = renderTable({
        data: rows("a", "b"),
        scope: "filtered",
      });

      act(() => {
        toggleAllSelected(result.current.table, true);
      });
      expect(getIsAllSelected(result.current.table)).toBe(true);

      rerender({ data: rows("a"), scope: "filtered" });

      // Deriving `selectedIds` from getSelectedRowModel() alone would leave
      // this true-but-stale, because the header counts raw state (#359).
      expect(result.current.selectedIds).toEqual(["a"]);
      expect(getIsAllSelected(result.current.table)).toBe(true);
      expect(Object.keys(result.current.table.getState().rowSelection)).toEqual(
        ["a"],
      );
    });

    it("keeps a selection whose rows are merely on another page (#307)", () => {
      const { result } = renderTable({
        data: rows("a", "b", "c", "d"),
        scope: "page",
        pageSize: 2,
      });

      act(() => {
        result.current.table.getRowModel().rows[0].toggleSelected(true);
      });
      act(() => {
        result.current.table.nextPage();
      });

      // Pruning is scoped to the filtered row model, not the page — paging away
      // from a selected row must not silently deselect it.
      expect(result.current.selectedIds).toEqual(["a"]);
    });

    it("does not resurrect ids the caller cleared (#307)", () => {
      const { result } = renderTable({
        data: rows("a", "b"),
        scope: "filtered",
      });

      act(() => {
        toggleAllSelected(result.current.table, true);
      });
      act(() => {
        result.current.clearSelection();
      });

      expect(result.current.selectedIds).toEqual([]);
      expect(Object.keys(result.current.table.getState().rowSelection)).toEqual(
        [],
      );
    });
  });

  describe("selectAllScope", () => {
    it("selects only the current page under page scope", () => {
      const { result } = renderTable({
        data: rows("a", "b", "c", "d", "e"),
        scope: "page",
        pageSize: 2,
      });

      act(() => {
        toggleAllSelected(result.current.table, true);
      });

      expect(result.current.selectedIds).toEqual(["a", "b"]);
    });

    it("selects every filtered row under filtered scope", () => {
      const { result } = renderTable({
        data: rows("a", "b", "c", "d", "e"),
        scope: "filtered",
        pageSize: 2,
      });

      act(() => {
        toggleAllSelected(result.current.table, true);
      });

      expect(result.current.selectedIds).toEqual(["a", "b", "c", "d", "e"]);
    });

    it("reports the header checkbox against the scope, not against every row", () => {
      const { result } = renderTable({
        data: rows("a", "b", "c", "d"),
        scope: "page",
        pageSize: 2,
      });

      act(() => {
        result.current.table.getRowModel().rows[0].toggleSelected(true);
        result.current.table.getRowModel().rows[1].toggleSelected(true);
      });

      // Every row on this page is selected, but only half the table is. Page
      // scope says checked; filtered scope would say indeterminate, and that
      // difference is the whole reason the parameter is required (#359, #382).
      expect(getIsAllSelected(result.current.table)).toBe(true);
      expect(result.current.table.getIsAllRowsSelected()).toBe(false);
    });

    it("does not mark a page indeterminate because another page holds a selection", () => {
      const { result } = renderTable({
        data: rows("a", "b", "c", "d"),
        scope: "page",
        pageSize: 2,
      });

      act(() => {
        result.current.table.nextPage();
      });
      act(() => {
        result.current.table.getRowModel().rows[0].toggleSelected(true);
      });
      act(() => {
        result.current.table.previousPage();
      });

      // Nothing on page 1 is selected. Reading the all-check at page scope but
      // the some-check globally renders this checkbox indeterminate anyway.
      expect(
        result.current.table.getRowModel().rows.map((row) => row.id),
      ).toEqual(["a", "b"]);
      expect(getIsAllSelected(result.current.table)).toBe(false);
    });

    it("reports indeterminate under filtered scope for the same selection", () => {
      const { result } = renderTable({
        data: rows("a", "b", "c", "d"),
        scope: "filtered",
        pageSize: 2,
      });

      act(() => {
        result.current.table.getRowModel().rows[0].toggleSelected(true);
        result.current.table.getRowModel().rows[1].toggleSelected(true);
      });

      expect(getIsAllSelected(result.current.table)).toBe("indeterminate");
    });

    it("clears ids outside the current scope, which deselect-all leaks", () => {
      const { result } = renderTable({
        data: rows("a", "b", "c", "d"),
        scope: "page",
        pageSize: 2,
      });

      act(() => {
        toggleAllSelected(result.current.table, true);
      });
      act(() => {
        result.current.table.nextPage();
      });
      act(() => {
        toggleAllSelected(result.current.table, true);
      });
      expect(result.current.selectedIds).toEqual(["a", "b", "c", "d"]);

      // The leak, demonstrated: deselect-all under page scope clears this page
      // and silently leaves the other page's ids selected. That is v8 behaviour
      // with no escape hatch (#355) — which is why clearSelection exists as a
      // separate operation rather than as an argument to deselect-all.
      act(() => {
        toggleAllSelected(result.current.table, false);
      });
      expect(result.current.selectedIds).toEqual(["a", "b"]);

      act(() => {
        result.current.clearSelection();
      });
      expect(result.current.selectedIds).toEqual([]);
    });

    it("enables no row selection at all when `selection` is omitted", () => {
      const { result } = renderTable({ data: rows("a", "b") });

      act(() => {
        result.current.table.getRowModel().rows[0].toggleSelected(true);
      });

      expect(result.current.selectedIds).toEqual([]);
    });
  });

  describe("the store adapter (#377)", () => {
    it("reads and writes sorting through an injected store instead of local state", () => {
      const writes: unknown[] = [];
      let sorting: { id: string; desc: boolean }[] = [];

      const { result, rerender } = renderHook(() => {
        const store: TableStore = {
          state: { sorting, globalFilter: "", pageIndex: 0 },
          setState: (patch) => {
            writes.push(patch);
            if (patch.sorting) sorting = patch.sorting;
          },
        };
        return useTableState<Row>({
          data: rows("a", "b"),
          columns,
          getRowId: (row) => row.id,
          store,
        });
      });

      act(() => {
        result.current.table.getColumn("name")?.toggleSorting(true);
      });

      expect(writes).toEqual([{ sorting: [{ id: "name", desc: true }] }]);

      rerender();
      expect(result.current.table.getState().sorting).toEqual([
        { id: "name", desc: true },
      ]);
    });

    it("writes exactly one slice per call, never two", () => {
      const writes: Record<string, unknown>[] = [];
      const store: TableStore = {
        state: { sorting: [], globalFilter: "", pageIndex: 0 },
        setState: (patch) => writes.push(patch),
      };

      const { result } = renderTable({
        data: rows("a", "b", "c"),
        scope: "filtered",
        store,
      });

      act(() => {
        result.current.table.setGlobalFilter("row a");
      });

      // #377 rests on this: the hook removed its hand-rolled page reset, so a
      // single-key patch is all the store ever has to batch.
      expect(writes).toHaveLength(1);
      expect(Object.keys(writes[0])).toEqual(["globalFilter"]);
    });

    it("keeps state local when no store is injected", () => {
      const { result } = renderTable({ data: rows("a", "b") });

      act(() => {
        result.current.table.getColumn("name")?.toggleSorting(true);
      });

      expect(result.current.table.getState().sorting).toEqual([
        { id: "name", desc: true },
      ]);
    });
  });

  describe("pagination (#360)", () => {
    it("paginates inside TanStack when a pageSize is given", () => {
      const { result } = renderTable({
        data: rows("a", "b", "c"),
        pageSize: 2,
      });

      expect(result.current.table.getRowModel().rows).toHaveLength(2);
      expect(result.current.table.getPageCount()).toBe(2);
    });

    it("treats the absence of pageSize as a model: manual pagination, no slicing", () => {
      const { result } = renderTable({ data: rows("a", "b", "c") });

      expect(result.current.table.options.manualPagination).toBe(true);
      expect(result.current.table.getRowModel().rows).toHaveLength(3);
    });

    it("arms auto-reset one render after rows first arrive, not on arrival (#381)", () => {
      const { result, rerender } = renderTable({ data: [], pageSize: 2 });

      // Rows have not arrived, so a reset here would fire against a page a
      // render-time clamp had already raised, stripping a deep link.
      expect(result.current.table.options.autoResetPageIndex).toBe(false);

      rerender({ data: rows("a", "b", "c"), pageSize: 2 });
      rerender({ data: rows("a", "b", "c"), pageSize: 2 });

      expect(result.current.table.options.autoResetPageIndex).toBe(true);
    });

    it("resets the page when pageSize changes, the one reset auto-reset cannot see", () => {
      // One array, reused: if `data` identity changed too, this could not tell
      // the pageSize reset from an ordinary auto-reset on a data change, and
      // would pass for the wrong reason.
      const data = rows("a", "b", "c", "d", "e", "f");
      const { result, rerender } = renderTable({ data, pageSize: 2 });

      act(() => {
        result.current.table.setPageIndex(2);
      });
      expect(result.current.table.getState().pagination.pageIndex).toBe(2);

      // A page-size change alters no `data` identity, so TanStack provably
      // never sees it (#360).
      rerender({ data, pageSize: 3 });

      expect(result.current.table.getState().pagination.pageIndex).toBe(0);
    });
  });

  describe("row identity", () => {
    it("keys rows by the supplied getRowId, never by position", () => {
      const { result, rerender } = renderTable({
        data: rows("a", "b"),
        scope: "filtered",
      });

      act(() => {
        result.current.table.getRowModel().rows[1].toggleSelected(true);
      });
      expect(result.current.selectedIds).toEqual(["b"]);

      // Same length, different objects at the same positions. Index-based ids
      // would silently re-point the selection at a different row (#355).
      rerender({ data: rows("b", "a"), scope: "filtered" });

      expect(result.current.selectedIds).toEqual(["b"]);
      expect(result.current.selectedRows[0].name).toBe("row b");
    });
  });
});

describe("encodeRowId (#383)", () => {
  it("keeps a delimiter inside a field from splitting the id", () => {
    // The live case: Status takes the literal value `Post-Processed`, so the
    // bare `-` join it replaced was ambiguous.
    expect(encodeRowId(["1", "Post-Processed", "nzb"])).not.toEqual(
      encodeRowId(["1", "Post", "Processed|nzb"]),
    );
    expect(encodeRowId(["1", "Post-Processed", "nzb"])).toEqual(
      encodeRowId(["1", "Post-Processed", "nzb"]),
    );
  });

  it("keeps null, empty string and the string 'null' distinct", () => {
    // ImportTable's `Volume || "null"` collapsed the first two, which SQL
    // groups separately (#364).
    const ids = [
      encodeRowId(["a", null]),
      encodeRowId(["a", ""]),
      encodeRowId(["a", "null"]),
    ];

    expect(new Set(ids).size).toBe(3);
  });

  it("is stable for the same input", () => {
    expect(encodeRowId(["a", 1, null])).toBe(encodeRowId(["a", 1, null]));
  });
});
