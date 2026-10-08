import { describe, expect, it } from "vitest";
import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  it("hydrates and displays a comic scan started from another page", async () => {
    server.use(
      http.get("/api/import/comic/progress", () =>
        HttpResponse.json({
          status: "scanning",
          progress: {
            series_found: 12,
            series_matched: 8,
            current_series: "Absolute Batman",
          },
          scan_id: null,
          results: null,
        }),
      ),
    );

    render(<ImportPage />);

    expect(await screen.findByText("Absolute Batman")).toBeTruthy();
    expect(screen.getByRole("button", { name: "scanning" })).toBeTruthy();
  });

  it("keeps a background comic scan failure visible", async () => {
    server.use(
      http.get("/api/import/comic/progress", () =>
        HttpResponse.json({
          status: "error",
          progress: { errors: ["ComicVine is unavailable"] },
          scan_id: null,
          results: null,
        }),
      ),
    );

    render(<ImportPage />);

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Comic library scan failed: ComicVine is unavailable",
    );
  });

  it("shows when an existing comic series was reconciled from disk", async () => {
    server.use(
      http.get("/api/import", () =>
        HttpResponse.json({
          imports: [],
          pagination: { total: 0, limit: 50, offset: 0, has_more: false },
          summary: { group_count: 0, file_count: 0 },
        }),
      ),
      http.get("/api/import/comic/progress", () =>
        HttpResponse.json({
          status: "completed",
          progress: { series_reconciled: 1 },
          scan_id: "scan-1",
          results: [
            {
              series_name: "Absolute Batman (2024)",
              file_count: 22,
              matched: false,
              already_in_library: true,
              reconciled: true,
              existing_comic_id: "160294",
              match: null,
            },
          ],
        }),
      ),
    );

    render(<ImportPage />);

    expect(
      await screen.findByText(/No new series found in directory/),
    ).toBeTruthy();
    expect(
      screen.getByText("Reconciled 1 existing comic series."),
    ).toBeTruthy();
  });

  it("puts matched scan candidates first and sorts each group alphabetically", async () => {
    server.use(
      http.get("/api/import", () =>
        HttpResponse.json({
          imports: [],
          pagination: {
            total: 0,
            limit: 50,
            offset: 0,
            has_more: false,
          },
          summary: { group_count: 0, file_count: 0 },
        }),
      ),
      http.get("/api/import/comic/progress", () =>
        HttpResponse.json({
          status: "completed",
          progress: {},
          scan_id: "scan-1",
          results: [
            { series_name: "Zeta Unmatched", file_count: 1, matched: false },
            {
              series_name: "Zeta Matched",
              file_count: 1,
              matched: true,
              match: {
                comicid: "2",
                name: "Zeta Match Metadata",
                confidence: 100,
              },
            },
            { series_name: "Alpha Unmatched", file_count: 1, matched: false },
            {
              series_name: "Alpha Matched",
              file_count: 1,
              matched: true,
              match: {
                comicid: "1",
                name: "Alpha Match Metadata",
                confidence: 100,
              },
            },
          ],
        }),
      ),
    );

    render(<ImportPage />);

    const alphaMatched = await screen.findByText("Alpha Matched");
    const zetaMatched = screen.getByText("Zeta Matched");
    const alphaUnmatched = screen.getByText("Alpha Unmatched");
    const zetaUnmatched = screen.getByText("Zeta Unmatched");

    expect(
      alphaMatched.compareDocumentPosition(zetaMatched) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      zetaMatched.compareDocumentPosition(alphaUnmatched) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      alphaUnmatched.compareDocumentPosition(zetaUnmatched) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("clears imported manga results and keeps a durable success summary", async () => {
    let scanStarted = false;
    let confirmed = false;
    server.use(
      http.get("/api/import/manga/progress", () =>
        HttpResponse.json({
          status: scanStarted ? "completed" : null,
          progress: {},
          scan_id: scanStarted && !confirmed ? "scan-1" : null,
          results:
            scanStarted && !confirmed
              ? [
                  {
                    series_name: "Berserk",
                    file_count: 42,
                    matched: true,
                    match: {
                      comicid: "mal-33",
                      name: "Berserk",
                      year: "1989",
                      confidence: 100,
                      source: "mal",
                    },
                  },
                ]
              : null,
        }),
      ),
      http.post("/api/import/manga/scan", () => {
        scanStarted = true;
        return HttpResponse.json({ success: true, message: "started" });
      }),
      http.post("/api/import/manga/confirm", () => {
        confirmed = true;
        return HttpResponse.json({ success: true, imported: 1, errors: [] });
      }),
    );

    const user = userEvent.setup();
    render(<ImportPage />);

    const scanButtons = await screen.findAllByRole("button", { name: "scan" });
    await user.click(scanButtons[1]);
    await user.click(
      await screen.findByRole("button", { name: "Import Selected (1)" }),
    );

    expect((await screen.findByRole("status")).textContent).toContain(
      "Imported 1 manga series",
    );
    expect(
      screen.queryByRole("button", { name: "Import Selected (1)" }),
    ).toBeNull();
  });

  it("clears imported comic results with the comic progress key", async () => {
    let confirmed = false;
    server.use(
      http.get("/api/import/comic/progress", () =>
        HttpResponse.json({
          status: "completed",
          progress: {},
          scan_id: confirmed ? null : "scan-1",
          results: confirmed
            ? null
            : [
                {
                  series_name: "Absolute Batman",
                  file_count: 22,
                  matched: true,
                  match: {
                    comicid: "160294",
                    name: "Absolute Batman",
                    year: "2024",
                    publisher: "DC Comics",
                    confidence: 100,
                  },
                },
              ],
        }),
      ),
      http.post("/api/import/comic/confirm", () => {
        confirmed = true;
        return HttpResponse.json({ success: true, imported: 1, errors: [] });
      }),
    );

    const user = userEvent.setup();
    render(<ImportPage />);

    await user.click(
      await screen.findByRole("button", { name: "Import Selected (1)" }),
    );

    expect((await screen.findByRole("status")).textContent).toContain(
      "Imported 1 comic series",
    );
    expect(
      screen.queryByRole("button", { name: "Import Selected (1)" }),
    ).toBeNull();
  });

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

  it("keeps Tab inside MatchModal and returns focus to the matching row on Escape", async () => {
    server.use(
      http.get("/api/import", () =>
        HttpResponse.json({
          imports: [
            makeGroup(),
            makeGroup({
              DynamicName: "folder:manga-b",
              ComicName: "Manga B",
              files: [
                makeFile({
                  impID: "imp-3",
                  ComicFilename: "chapter 1.cbz",
                  ComicLocation: "/imports/Manga B/chapter 1.cbz",
                }),
              ],
              FileCount: 1,
            }),
          ],
          pagination: { total: 2, limit: 50, offset: 0, has_more: false },
          summary: { group_count: 2, file_count: 3 },
        }),
      ),
    );

    const user = userEvent.setup();
    render(<ImportPage />);

    const matchButtons = await screen.findAllByRole("button", {
      name: "Match import",
    });
    expect(matchButtons).toHaveLength(2);
    await user.click(matchButtons[1]);

    const dialog = await screen.findByRole("dialog", { name: "Match Import" });
    for (let i = 0; i < 20; i += 1) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    await waitFor(() => {
      expect(document.activeElement).toBe(
        screen.getAllByRole("button", { name: "Match import" })[1],
      );
    });
  });
});
