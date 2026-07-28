import { describe, expect, it } from "vitest";
import {
  sortParser,
  tableUrlParams,
} from "@/components/data-table/tableUrlStore";

/**
 * The caller-side URL adapter. Kept separate from useTableState.test.tsx
 * because #377's boundary is that `useTableState.ts` imports nothing from
 * `tableUrlStore.ts` — a test suite that spans both would quietly couple the
 * layer the decision exists to keep apart.
 */
describe("tableUrlParams (#377)", () => {
  it("floors a negative page from the URL instead of passing it through", () => {
    // The URL is user-supplied and `?page=-1` parses cleanly to -1, which would
    // reach TanStack as a negative pageIndex.
    expect(tableUrlParams.page.parse("-1")).toBe(0);
    expect(tableUrlParams.page.parse("2")).toBe(2);
  });

  it("leaves an out-of-range high page alone, which is the caller's concern", () => {
    // Clamping here cannot tell "rows have not arrived" from "genuinely out of
    // range" — the rewrite that tries is the bug #381 fixed.
    expect(tableUrlParams.page.parse("99")).toBe(99);
  });

  it("omits a sort equal to the default rather than serialising it (#377)", () => {
    const withDefault = sortParser.withDefault({ id: "name", desc: false });
    expect(
      withDefault.eq?.(
        { id: "name", desc: false },
        { id: "name", desc: false },
      ),
    ).toBe(true);
    expect(
      withDefault.eq?.({ id: "name", desc: true }, { id: "name", desc: false }),
    ).toBe(false);
  });
});
