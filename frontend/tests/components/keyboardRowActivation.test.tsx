import { useEffect } from "react";
import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { NuqsAdapter } from "nuqs/adapters/react-router/v7";
import { fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { render, renderMinimal, screen } from "../test-utils";
import { server } from "../mocks/server";
import SeriesTable from "@/components/series/SeriesTable";
import WantedTable from "@/components/queue/WantedTable";
import { useWantedColumns } from "@/components/queue/wantedColumns";
import { useTableState } from "@/components/data-table/useTableState";
import MatchModal from "@/components/import/MatchModal";
import type { Comic, ImportGroup, Issue } from "@/types";

function seriesRow(id: string, name: string): Comic {
  return {
    ComicID: id,
    ComicName: name,
    ComicPublisher: "Publisher",
    ComicYear: "2024",
    Status: "Active",
    Have: 0,
    Total: 1,
  } as Comic;
}

function WantedHarness({
  rows,
  onSelectionChange,
}: {
  rows: Issue[];
  onSelectionChange?: (ids: string[]) => void;
}) {
  const columns = useWantedColumns();
  const { table, selectedIds } = useTableState({
    data: rows,
    columns,
    getRowId: (row) => row.IssueID,
    selection: { scope: "filtered" },
  });
  useEffect(() => {
    onSelectionChange?.(selectedIds);
  }, [selectedIds, onSelectionChange]);
  return <WantedTable table={table} />;
}

const comicGroup: ImportGroup = {
  DynamicName: "amazing-spider-man",
  ComicName: "Amazing Spider-Man",
  Volume: null,
  ComicYear: "2020",
  FileCount: 1,
  Status: "Unmatched",
  SRID: null,
  ComicID: "4050-12345",
  MatchConfidence: null,
  SuggestedComicID: null,
  SuggestedComicName: null,
  files: [],
};

describe("keyboard row activation", () => {
  it("opens a library series, a wanted series, and a match result without a pointer", async () => {
    const user = userEvent.setup();
    window.history.pushState({}, "", "/library");

    const { unmount: unmountSeries } = render(
      <NuqsAdapter>
        <SeriesTable data={[seriesRow("4050-1", "Saga")]} />
      </NuqsAdapter>,
    );

    const seriesTitle = screen.getByTestId("series-row-title");
    seriesTitle.focus();
    await user.keyboard("{Enter}");
    expect(window.location.pathname).toBe("/library/4050-1");
    unmountSeries();

    window.history.pushState({}, "", "/wanted");
    const { unmount: unmountWanted } = render(
      <WantedHarness
        rows={[
          {
            IssueID: "issue-1",
            ComicID: "4050-2",
            ComicName: "East of West",
            Issue_Number: "1",
            IssueName: "Chapter 1",
            IssueDate: "2026-01-01",
            Status: "Wanted",
          } as Issue,
        ]}
      />,
    );

    const wantedTitle = screen.getByRole("link", { name: "East of West" });
    expect(wantedTitle.tagName).toBe("A");
    expect(wantedTitle.getAttribute("href")).toBe("/library/4050-2");
    wantedTitle.focus();
    await user.keyboard("{Enter}");
    expect(window.location.pathname).toBe("/library/4050-2");
    unmountWanted();

    server.use(
      http.post("/api/search/comics", async () => {
        return HttpResponse.json({
          results: [
            {
              comicid: "12345",
              name: "Amazing Spider-Man",
              comicyear: "2022",
              publisher: "Marvel",
            },
            {
              comicid: "67890",
              name: "Ultimate Spider-Man",
              comicyear: "2024",
              publisher: "Marvel",
            },
          ],
          pagination: { total: 2, limit: 20, offset: 0, returned: 2 },
        });
      }),
    );

    renderMinimal(
      <MatchModal
        isOpen
        onClose={() => undefined}
        importGroup={comicGroup}
        onMatch={() => undefined}
      />,
    );

    const matchResult = await screen.findByRole("button", {
      name: /Amazing Spider-Man/,
    });
    const matchSelected = screen.getByRole("button", {
      name: "Match Selected",
    });
    expect(matchSelected).toHaveProperty("disabled", true);

    matchResult.focus();
    await user.keyboard("{Enter}");
    await waitFor(() => {
      expect(matchSelected).toHaveProperty("disabled", false);
    });
  });

  it("selects a Wanted row with Space on the checkbox without navigating", async () => {
    window.history.pushState({}, "", "/wanted");
    let selectedIds: string[] = [];
    render(
      <WantedHarness
        rows={[
          {
            IssueID: "issue-1",
            ComicID: "4050-2",
            ComicName: "East of West",
            Issue_Number: "1",
            IssueName: "Chapter 1",
            IssueDate: "2026-01-01",
            Status: "Wanted",
          } as Issue,
        ]}
        onSelectionChange={(ids) => {
          selectedIds = ids;
        }}
      />,
    );

    const rowCheckbox = screen.getAllByRole("checkbox").slice(1)[0];
    rowCheckbox.focus();
    fireEvent.keyDown(rowCheckbox, { key: " ", code: "Space" });
    fireEvent.keyUp(rowCheckbox, { key: " ", code: "Space" });
    await waitFor(() => {
      expect(selectedIds).toEqual(["issue-1"]);
    });
    expect(window.location.pathname).toBe("/wanted");
  });
});
