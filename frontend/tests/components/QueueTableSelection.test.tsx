import { useEffect } from "react";
import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen } from "../test-utils";
import WantedTable from "@/components/queue/WantedTable";
import { useWantedColumns } from "@/components/queue/wantedColumns";
import UpcomingTable from "@/components/queue/UpcomingTable";
import { useUpcomingColumns } from "@/components/queue/upcomingColumns";
import { useTableState } from "@/components/data-table/useTableState";
import type { Issue } from "@/types";

/**
 * Both tables set getRowId to the IssueID, then decoded the resulting selection
 * keys as array indices. issues[parseInt("md-csm-ch165")] is undefined, every id
 * was filtered out, and the bulk action bar reported nothing selected -- so
 * every bulk action silently ran on zero issues.
 *
 * These are the two per-site pins of that decode: each table's real select
 * column, driven through its real DOM, must report entity ids. The generic
 * halves of the old suite -- non-adjacent multi-select, header select-all,
 * deselect, not resurrecting cleared ids, dropping ids whose rows left --
 * moved to useTableState.test.tsx with their #307 reference when #395 moved
 * the table instance into the pages.
 *
 * The harnesses stand in for WantedPage / MyReleasesView as they now are:
 * calling useTableState with the shared columns, passing `table` down, and
 * reading `selectedIds` off the hook.
 */

function issues(count: number): Issue[] {
  return Array.from({ length: count }, (_, index) => {
    const number = index + 1;
    return {
      IssueID: `issue-${number}`,
      ComicID: "series-1",
      ComicName: "Chainsaw Man",
      Issue_Number: String(number),
      IssueName: `Chapter ${number}`,
      IssueDate: "2026-01-01",
      Status: "Wanted",
    } as Issue;
  });
}

function useReportedSelection(
  selectedIds: string[],
  onSelectionChange: (ids: string[]) => void,
) {
  useEffect(() => {
    if (selectedIds.length > 0) onSelectionChange(selectedIds);
  }, [selectedIds, onSelectionChange]);
}

function WantedHarness({
  rows,
  onSelectionChange,
}: {
  rows: Issue[];
  onSelectionChange: (ids: string[]) => void;
}) {
  const columns = useWantedColumns();
  const { table, selectedIds } = useTableState({
    data: rows,
    columns,
    getRowId: (row) => row.IssueID,
    selection: { scope: "filtered" },
    initialSorting: [{ id: "DateAdded", desc: true }],
  });
  useReportedSelection(selectedIds, onSelectionChange);

  return <WantedTable table={table} />;
}

function UpcomingHarness({
  rows,
  onSelectionChange,
}: {
  rows: Issue[];
  onSelectionChange: (ids: string[]) => void;
}) {
  const columns = useUpcomingColumns();
  const { table, selectedIds } = useTableState({
    data: rows,
    columns,
    getRowId: (row) => row.IssueID,
    selection: { scope: "filtered" },
    initialSorting: [{ id: "IssueDate", desc: false }],
  });
  useReportedSelection(selectedIds, onSelectionChange);

  return <UpcomingTable table={table} />;
}

function rowCheckboxes(): HTMLElement[] {
  // checkboxes[0] is the header select-all toggle.
  return screen.getAllByRole("checkbox").slice(1);
}

function lastSelection(spy: ReturnType<typeof vi.fn>): string[] | undefined {
  return spy.mock.calls.at(-1)?.[0] as string[] | undefined;
}

describe("queue table selection", () => {
  it("reports the selected WantedTable issue by id", async () => {
    const user = userEvent.setup();
    const onSelectionChange = vi.fn();
    render(
      <WantedHarness rows={issues(3)} onSelectionChange={onSelectionChange} />,
    );

    await user.click(rowCheckboxes()[0]);

    expect(onSelectionChange).toHaveBeenCalled();
    expect(lastSelection(onSelectionChange)).toEqual(["issue-1"]);

    // The header checkbox is this table's own column wiring, not the hook's,
    // so it is driven through the DOM here.
    await user.click(screen.getAllByRole("checkbox")[0]);

    expect(lastSelection(onSelectionChange)?.sort()).toEqual([
      "issue-1",
      "issue-2",
      "issue-3",
    ]);
  });

  it("reports the selected UpcomingTable issue by id", async () => {
    const user = userEvent.setup();
    const onSelectionChange = vi.fn();
    render(
      <UpcomingHarness
        rows={issues(3)}
        onSelectionChange={onSelectionChange}
      />,
    );

    await user.click(rowCheckboxes()[0]);

    expect(onSelectionChange).toHaveBeenCalled();
    expect(lastSelection(onSelectionChange)).toEqual(["issue-1"]);

    await user.click(screen.getAllByRole("checkbox")[0]);

    expect(lastSelection(onSelectionChange)?.sort()).toEqual([
      "issue-1",
      "issue-2",
      "issue-3",
    ]);
  });
});
