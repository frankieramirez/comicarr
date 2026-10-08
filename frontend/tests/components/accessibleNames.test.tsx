import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, renderMinimal, screen } from "../test-utils";
import ImportTable from "@/components/import/ImportTable";
import {
  getImportGroupRowId,
  useImportColumns,
} from "@/components/import/importColumns";
import LibraryScanResults from "@/components/import/LibraryScanResults";
import MatchModal from "@/components/import/MatchModal";
import WantedTable from "@/components/queue/WantedTable";
import UpcomingTable from "@/components/queue/UpcomingTable";
import { useWantedColumns } from "@/components/queue/wantedColumns";
import { useUpcomingColumns } from "@/components/queue/upcomingColumns";
import { useTableState } from "@/components/data-table/useTableState";
import ArcHeader from "@/components/storyarcs/ArcHeader";
import type {
  ImportFile,
  ImportGroup,
  Issue,
  ScanResult,
  StoryArc,
} from "@/types";

vi.mock("@/hooks/useStoryArcs", () => ({
  useDelStoryArc: () => ({ mutate: vi.fn(), isPending: false }),
  useWantAllArcIssues: () => ({ mutate: vi.fn(), isPending: false }),
  useRefreshStoryArc: () => ({ mutate: vi.fn(), isPending: false }),
}));

function assertEveryHasAccessibleName(role: "checkbox" | "button") {
  const all = screen.getAllByRole(role);
  const named = screen.getAllByRole(role, { name: /\S/ });
  expect(all.length).toBeGreaterThan(0);
  expect(named).toHaveLength(all.length);
}

function makeFile(overrides: Partial<ImportFile> = {}): ImportFile {
  return {
    impID: "1",
    ComicFilename: "chapter 1.cbz",
    ComicLocation: "/imports/Manga A/chapter 1.cbz",
    IssueNumber: "1",
    ComicYear: null,
    Status: "Unmatched",
    IgnoreFile: 0,
    MatchConfidence: null,
    SuggestedComicID: null,
    SuggestedComicName: null,
    SuggestedIssueID: null,
    MatchSource: null,
    ...overrides,
  };
}

function makeGroup(overrides: Partial<ImportGroup> = {}): ImportGroup {
  const files = overrides.files ?? [makeFile()];
  return {
    DynamicName: "folder:manga-a",
    ComicName: "Manga A",
    Volume: null,
    ComicYear: null,
    FileCount: files.length,
    Status: "Unmatched",
    SRID: null,
    ComicID: null,
    MatchConfidence: null,
    SuggestedComicID: null,
    SuggestedComicName: null,
    files,
    ...overrides,
  };
}

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

function ImportHarness({ imports }: { imports: ImportGroup[] }) {
  const columns = useImportColumns({});
  const { table } = useTableState({
    data: imports,
    columns,
    getRowId: getImportGroupRowId,
    selection: { scope: "filtered" },
    getRowCanExpand: (row) =>
      !!(row.original.files && row.original.files.length > 0),
  });
  return <ImportTable table={table} />;
}

function WantedHarness({ rows }: { rows: Issue[] }) {
  const columns = useWantedColumns();
  const { table } = useTableState({
    data: rows,
    columns,
    getRowId: (row) => row.IssueID,
    selection: { scope: "filtered" },
    initialSorting: [{ id: "DateAdded", desc: true }],
  });
  return <WantedTable table={table} />;
}

function UpcomingHarness({ rows }: { rows: Issue[] }) {
  const columns = useUpcomingColumns();
  const { table } = useTableState({
    data: rows,
    columns,
    getRowId: (row) => row.IssueID,
    selection: { scope: "filtered" },
    initialSorting: [{ id: "IssueDate", desc: false }],
  });
  return <UpcomingTable table={table} />;
}

const scanResults: ScanResult[] = [
  {
    series_name: "Saga",
    file_count: 2,
    matched: true,
    match: {
      comicid: "4050-1",
      name: "Saga",
      year: "2012",
      confidence: 0.9,
    },
  },
];

const arc: StoryArc = {
  StoryArcID: "arc-1",
  StoryArc: "Infinity Gauntlet",
  TotalIssues: 6,
  Have: 2,
  Total: 6,
  percent: 33,
  SpanYears: "1991",
  CV_ArcID: "123",
  Publisher: "Marvel",
  ArcImage: null,
};

describe("accessible names for unlabeled controls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("names ImportTable checkboxes and buttons", () => {
    renderMinimal(<ImportHarness imports={[makeGroup()]} />);
    assertEveryHasAccessibleName("checkbox");
    assertEveryHasAccessibleName("button");
  });

  it("names WantedTable checkboxes and buttons", () => {
    render(<WantedHarness rows={issues(1)} />);
    assertEveryHasAccessibleName("checkbox");
    assertEveryHasAccessibleName("button");
  });

  it("names UpcomingTable checkboxes and buttons", () => {
    render(<UpcomingHarness rows={issues(1)} />);
    assertEveryHasAccessibleName("checkbox");
    assertEveryHasAccessibleName("button");
  });

  it("names LibraryScanResults checkboxes and buttons", () => {
    renderMinimal(
      <LibraryScanResults
        results={scanResults}
        scanId="scan-1"
        onConfirm={vi.fn()}
        isConfirming={false}
        type="comic"
      />,
    );
    assertEveryHasAccessibleName("checkbox");
    assertEveryHasAccessibleName("button");
  });

  it("names the MatchModal close button", () => {
    renderMinimal(
      <MatchModal
        isOpen
        onClose={vi.fn()}
        importGroup={makeGroup({ ComicName: "Amazing Spider-Man" })}
        onMatch={vi.fn()}
      />,
    );
    assertEveryHasAccessibleName("button");
    expect(screen.getByRole("button", { name: "Close" })).toBeTruthy();
  });

  it("names the ArcHeader delete button", () => {
    render(<ArcHeader arc={arc} />);
    assertEveryHasAccessibleName("button");
    expect(
      screen.getByRole("button", { name: "Delete story arc" }),
    ).toBeTruthy();
  });
});
