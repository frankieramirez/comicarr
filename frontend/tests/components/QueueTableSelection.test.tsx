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

async function selectFirstRow() {
  const user = userEvent.setup();
  const checkboxes = screen.getAllByRole("checkbox");
  // checkboxes[0] is the header select-all toggle.
  await user.click(checkboxes[1]);
}

describe("queue table selection", () => {
  it("reports the selected WantedTable issue by id", async () => {
    const onSelectionChange = vi.fn();
    render(
      <WantedTable issues={issues(3)} onSelectionChange={onSelectionChange} />,
    );

    await selectFirstRow();

    expect(onSelectionChange).toHaveBeenCalled();
    expect(onSelectionChange.mock.calls.at(-1)?.[0]).toEqual(["issue-1"]);
  });

  it("reports the selected UpcomingTable issue by id", async () => {
    const onSelectionChange = vi.fn();
    render(
      <UpcomingTable issues={issues(3)} onSelectionChange={onSelectionChange} />,
    );

    await selectFirstRow();

    expect(onSelectionChange).toHaveBeenCalled();
    expect(onSelectionChange.mock.calls.at(-1)?.[0]).toEqual(["issue-1"]);
  });

  it("drops an issue from the selection when it is unchecked", async () => {
    const user = userEvent.setup();
    const onSelectionChange = vi.fn();
    render(
      <WantedTable issues={issues(3)} onSelectionChange={onSelectionChange} />,
    );

    await selectFirstRow();
    await user.click(screen.getAllByRole("checkbox")[1]);

    expect(onSelectionChange.mock.calls.at(-1)?.[0]).toEqual([]);
  });
});
