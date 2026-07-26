import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen } from "../test-utils";
import WantedTable from "@/components/queue/WantedTable";
import UpcomingTable from "@/components/queue/UpcomingTable";
import type { Issue } from "@/types";

/**
 * Both tables set getRowId to the IssueID, then decoded the resulting selection
 * keys as array indices. issues[parseInt("md-csm-ch165")] is undefined, every id
 * was filtered out, and the bulk action bar reported nothing selected -- so
 * every bulk action silently ran on zero issues.
 *
 * Selection is now owned by the page and passed back down, so these tests drive
 * the tables the way the pages do: a controlled harness that echoes each
 * reported selection back as the `selectedIds` prop.
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

type QueueTable = typeof WantedTable | typeof UpcomingTable;

/**
 * Stands in for WantedPage / MyReleasesView: holds the selection, feeds it back
 * to the table, and exposes the page-side Clear button plus a data swap.
 */
function SelectionHarness({
  table: Table,
  rows,
  onSelectionChange,
}: {
  table: QueueTable;
  rows: Issue[];
  onSelectionChange: (ids: string[]) => void;
}) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [data, setData] = useState(rows);

  return (
    <div>
      <button type="button" onClick={() => setSelectedIds([])}>
        Clear Selection
      </button>
      <button type="button" onClick={() => setData(data.slice(0, 1))}>
        Drop rows
      </button>
      <Table
        issues={data}
        selectedIds={selectedIds}
        onSelectionChange={(ids: string[]) => {
          setSelectedIds(ids);
          onSelectionChange(ids);
        }}
      />
    </div>
  );
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
      <SelectionHarness
        table={WantedTable}
        rows={issues(3)}
        onSelectionChange={onSelectionChange}
      />,
    );

    await user.click(rowCheckboxes()[0]);

    expect(onSelectionChange).toHaveBeenCalled();
    expect(lastSelection(onSelectionChange)).toEqual(["issue-1"]);
  });

  it("reports the selected UpcomingTable issue by id", async () => {
    const user = userEvent.setup();
    const onSelectionChange = vi.fn();
    render(
      <SelectionHarness
        table={UpcomingTable}
        rows={issues(3)}
        onSelectionChange={onSelectionChange}
      />,
    );

    await user.click(rowCheckboxes()[0]);

    expect(onSelectionChange).toHaveBeenCalled();
    expect(lastSelection(onSelectionChange)).toEqual(["issue-1"]);
  });

  it("reports ids, not row positions, for a non-adjacent multi-row selection", async () => {
    const user = userEvent.setup();
    const onSelectionChange = vi.fn();
    render(
      <SelectionHarness
        table={WantedTable}
        rows={issues(4)}
        onSelectionChange={onSelectionChange}
      />,
    );

    await user.click(rowCheckboxes()[1]);
    await user.click(rowCheckboxes()[3]);

    // A position-based decode would report issue-1/issue-2 here.
    expect(lastSelection(onSelectionChange)?.sort()).toEqual([
      "issue-2",
      "issue-4",
    ]);
  });

  it("reports every id for the header select-all toggle", async () => {
    const user = userEvent.setup();
    const onSelectionChange = vi.fn();
    render(
      <SelectionHarness
        table={WantedTable}
        rows={issues(3)}
        onSelectionChange={onSelectionChange}
      />,
    );

    await user.click(screen.getAllByRole("checkbox")[0]);

    expect(lastSelection(onSelectionChange)?.sort()).toEqual([
      "issue-1",
      "issue-2",
      "issue-3",
    ]);
  });

  it("drops an issue from the selection when it is unchecked", async () => {
    const user = userEvent.setup();
    const onSelectionChange = vi.fn();
    render(
      <SelectionHarness
        table={WantedTable}
        rows={issues(3)}
        onSelectionChange={onSelectionChange}
      />,
    );

    await user.click(rowCheckboxes()[0]);
    await user.click(rowCheckboxes()[0]);

    expect(lastSelection(onSelectionChange)).toEqual([]);
  });

  it("does not resurrect ids the page cleared", async () => {
    const user = userEvent.setup();
    const onSelectionChange = vi.fn();
    render(
      <SelectionHarness
        table={WantedTable}
        rows={issues(4)}
        onSelectionChange={onSelectionChange}
      />,
    );

    await user.click(rowCheckboxes()[0]);
    await user.click(rowCheckboxes()[1]);
    expect(lastSelection(onSelectionChange)?.sort()).toEqual([
      "issue-1",
      "issue-2",
    ]);

    await user.click(screen.getByRole("button", { name: "Clear Selection" }));
    await user.click(rowCheckboxes()[3]);

    // Before selection was lifted to the page, the table kept its own copy and
    // reported issue-1 and issue-2 again -- skipping issues the user cleared.
    expect(lastSelection(onSelectionChange)).toEqual(["issue-4"]);
  });

  it("drops selected ids whose rows are no longer rendered", async () => {
    const user = userEvent.setup();
    const onSelectionChange = vi.fn();
    render(
      <SelectionHarness
        table={WantedTable}
        rows={issues(3)}
        onSelectionChange={onSelectionChange}
      />,
    );

    await user.click(rowCheckboxes()[0]);
    await user.click(rowCheckboxes()[2]);
    expect(lastSelection(onSelectionChange)?.sort()).toEqual([
      "issue-1",
      "issue-3",
    ]);

    await user.click(screen.getByRole("button", { name: "Drop rows" }));

    // issue-3 is gone from the data, so a bulk action must not still target it.
    expect(lastSelection(onSelectionChange)).toEqual(["issue-1"]);
  });
});
