import { describe, expect, it } from "vitest";
import { waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import ImportPage from "@/pages/ImportPage";
import type { ImportGroup } from "@/types";

type ImportFile = ImportGroup["files"][number];

function makeFile(overrides: Partial<ImportFile> = {}): ImportFile {
  return {
    impID: "imp-1",
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
  const files = overrides.files ?? [
    makeFile(),
    makeFile({
      impID: "imp-2",
      ComicFilename: "chapter 2.cbz",
      ComicLocation: "/imports/Manga A/chapter 2.cbz",
      IssueNumber: "2",
    }),
  ];

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

describe("ImportPage", () => {
  it("puts pending review before sources and scans when imports exist", async () => {
    server.use(
      http.get("/api/import", () =>
        HttpResponse.json({
          imports: [makeGroup()],
          pagination: { total: 1, limit: 50, offset: 0, has_more: false },
          summary: { group_count: 1, file_count: 2 },
        }),
      ),
    );

    render(<ImportPage />);

    await waitFor(() => {
      expect(screen.getByText("Manga A")).toBeTruthy();
    });

    expect(
      screen.getAllByText(/1 group · 2 files awaiting review/).length,
    ).toBeGreaterThan(0);

    const pendingHeader = screen.getByText("Files awaiting review");
    const sourcesHeader = screen.getByText("Sources and scans");
    expect(
      pendingHeader.compareDocumentPosition(sourcesHeader) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("shows scan action in the empty pending state when inbox is configured", async () => {
    server.use(
      http.get("/api/import", () =>
        HttpResponse.json({
          imports: [],
          pagination: { total: 0, limit: 50, offset: 0, has_more: false },
          summary: { group_count: 0, file_count: 0 },
        }),
      ),
      http.get("/api/config", () =>
        HttpResponse.json({
          comic_dir: "/comics",
          import_dir: "/imports",
          api_enabled: true,
        }),
      ),
    );

    render(<ImportPage />);

    await waitFor(() => {
      expect(screen.getByText("No pending imports")).toBeTruthy();
    });
    expect(screen.getByRole("button", { name: "Scan inbox now" })).toBeTruthy();
    expect(screen.getByText("Sources and scans")).toBeTruthy();
  });

  it("does not show zero pending counts when pending imports fail to load", async () => {
    server.use(
      http.get("/api/import", () =>
        HttpResponse.json({ error: "Unable to load" }, { status: 500 }),
      ),
    );

    render(<ImportPage />);

    await waitFor(() => {
      expect(
        screen.getAllByText("Unable to load pending imports").length,
      ).toBeGreaterThan(0);
    });
    expect(screen.queryByText(/0 groups · 0 files awaiting review/)).toBeNull();
    expect(
      screen.getByText("Resolve the loading error before reviewing imports."),
    ).toBeTruthy();
  });
});
