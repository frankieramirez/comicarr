import { describe, expect, it, vi } from "vitest";
import { waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import ImportPickPanel from "@/components/import/ImportPickPanel";
import ImportPage from "@/pages/ImportPage";
import { formatBytes, mergeCandidates, pickNote } from "@/lib/importPick";
import type {
  ImportCandidate,
  ImportGroup,
  ImportPickPanel as Panel,
} from "@/types";

function candidate(overrides: Partial<ImportCandidate> = {}): ImportCandidate {
  return {
    comic_id: "cv-2016",
    name: "BLAME!",
    year: "2016",
    publisher: "Vertical",
    issues: 6,
    have: 6,
    in_library: true,
    image: null,
    score: 72,
    ...overrides,
  };
}

function panel(overrides: Partial<Panel> = {}): Panel {
  return {
    group_name: "BLAME! Master Edition",
    match_name: "BLAME! Master Edition",
    years: [],
    source: "inbox",
    folder: "inbox/BLAME! Master Edition/",
    found_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
    total_bytes: 1_400_000_000,
    files: [
      {
        impID: "a",
        filename: "v01.cbz",
        bytes: 248_000_000,
        issue_number: "1",
      },
      {
        impID: "b",
        filename: "v02.cbz",
        bytes: 236_000_000,
        issue_number: "2",
      },
    ],
    confidence_bar: 80,
    reason: "tied",
    tied: 2,
    remembers: true,
    remembered: null,
    pick: "cv-2016",
    candidates: [
      candidate(),
      candidate({ comic_id: "cv-1998", year: "1998", publisher: "Kodansha" }),
    ],
    ...overrides,
  };
}

function group(overrides: Partial<ImportGroup> = {}): ImportGroup {
  return {
    DynamicName: "folder:blame",
    ComicName: "BLAME! Master Edition",
    Volume: null,
    ComicYear: null,
    FileCount: 2,
    Status: "Not Imported",
    SRID: null,
    ComicID: null,
    MatchConfidence: 72,
    SuggestedComicID: "cv-2016",
    SuggestedComicName: "BLAME!",
    files: ["a", "b"].map((impID, n) => ({
      impID,
      ComicFilename: `v0${n + 1}.cbz`,
      ComicLocation: `/inbox/BLAME! Master Edition/v0${n + 1}.cbz`,
      IssueNumber: String(n + 1),
      ComicYear: null,
      Status: "Not Imported",
      IgnoreFile: 0,
      MatchConfidence: 72,
      SuggestedComicID: "cv-2016",
      SuggestedComicName: "BLAME!",
      SuggestedIssueID: null,
      MatchSource: "inbox",
    })),
    ...overrides,
  };
}

function renderPanel(
  props: Partial<Parameters<typeof ImportPickPanel>[0]> = {},
) {
  const handlers = {
    onClose: vi.fn(),
    onImport: vi.fn(),
    onIgnore: vi.fn(),
    onDelete: vi.fn(),
    onSearchDifferent: vi.fn(),
  };
  render(
    <ImportPickPanel
      group={group()}
      bucket="needs_pick"
      rowId="row"
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

describe("importPick helpers", () => {
  it("formats sizes in decimal units", () => {
    expect(formatBytes(248_000_000)).toBe("248 MB");
    expect(formatBytes(1_400_000_000)).toBe("1.4 GB");
    expect(formatBytes(null)).toBeNull();
  });

  it("drops provider hits the library already holds", () => {
    const merged = mergeCandidates(
      [candidate({ score: 60 })],
      [
        candidate({ comic_id: "cv-2016", in_library: true, score: 99 }),
        candidate({ comic_id: "cv-new", in_library: false, score: 80 }),
      ],
    );
    expect(merged.map((c) => c.comic_id)).toEqual(["cv-new", "cv-2016"]);
  });

  it("explains each reason a group waits", () => {
    expect(pickNote(panel())).toBe(
      "Two series in your library share this title, so this one needs a check. Comicarr's pick is selected; your choice is remembered for future files from this folder.",
    );
    expect(
      pickNote(panel({ reason: "below_bar", remembers: false, tied: 1 })),
    ).toBe(
      "The best guess scored 72%, under your 80% auto-import bar. Comicarr's pick is selected.",
    );
    expect(
      pickNote(
        panel({
          reason: "remembered",
          remembered: {
            comic_id: "cv-2016",
            comic_name: "BLAME!",
            folder_name: "x",
            chosen_at: "",
          },
        }),
      ),
    ).toBe(
      "You matched this folder to BLAME! before, so that pick is selected.",
    );
    expect(
      pickNote(panel({ reason: "no_match", pick: null, remembers: false })),
    ).toBe("Nothing in your library looks like this.");
    expect(
      pickNote(
        panel({
          reason: "other_year",
          years: ["2026"],
          remembers: false,
          tied: 1,
        }),
      ),
    ).toBe(
      "The files name 2026, but BLAME! (2016) started in 2016. Files often carry the issue's cover year, so check it's the right volume. Comicarr's pick is selected.",
    );
  });
});

describe("ImportPickPanel", () => {
  it("opens on Comicarr's pick and imports the series chosen instead", async () => {
    server.use(
      http.post("/api/import/candidates", () => HttpResponse.json(panel())),
    );
    const handlers = renderPanel();

    const pick = await screen.findByRole("radio", { name: /BLAME! \(2016\)/ });
    expect(pick).toHaveProperty("checked", true);
    expect(
      screen.getByText("2 files · 1.4 GB · found in inbox 2h ago"),
    ).toBeTruthy();
    expect(screen.getByText("248 MB")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Import as BLAME! (2016)" }),
    ).toBeTruthy();

    await userEvent.click(
      screen.getByRole("radio", { name: /BLAME! \(1998\)/ }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Import as BLAME! (1998)" }),
    );
    expect(handlers.onImport).toHaveBeenCalledWith(
      expect.objectContaining({ comic_id: "cv-1998" }),
    );
  });

  it("asks a provider only when the library leaves the pick thin, and adds what it finds", async () => {
    const remote = vi.fn(() =>
      HttpResponse.json({
        candidates: [
          candidate({
            comic_id: "4050-9",
            name: "BLAME!",
            year: "1998",
            publisher: "Kodansha",
            in_library: false,
            score: 64,
          }),
        ],
        query: "BLAME!",
      }),
    );
    server.use(
      http.post("/api/import/candidates", () =>
        HttpResponse.json(
          panel({ reason: "below_bar", candidates: [candidate()], tied: 1 }),
        ),
      ),
      http.post("/api/import/candidates/remote", remote),
    );
    const handlers = renderPanel();

    const added = await screen.findByRole("radio", { name: /not in library/ });
    expect(remote).toHaveBeenCalledTimes(1);
    await userEvent.click(added);
    await userEvent.click(
      screen.getByRole("button", { name: "Add and import as BLAME! (1998)" }),
    );
    expect(handlers.onImport).toHaveBeenCalledWith(
      expect.objectContaining({ comic_id: "4050-9", in_library: false }),
    );
  });

  it("offers Unignore for ignored files and leaves the provider alone when remembered", async () => {
    const remote = vi.fn(() =>
      HttpResponse.json({ candidates: [], query: "" }),
    );
    server.use(
      http.post("/api/import/candidates", () =>
        HttpResponse.json(
          panel({
            reason: "remembered",
            candidates: [candidate()],
            remembered: {
              comic_id: "cv-2016",
              comic_name: "BLAME!",
              folder_name: "x",
              chosen_at: "",
            },
          }),
        ),
      ),
      http.post("/api/import/candidates/remote", remote),
    );
    const handlers = renderPanel({ bucket: "ignored" });

    await userEvent.click(
      await screen.findByRole("button", { name: "Unignore" }),
    );
    expect(handlers.onIgnore).toHaveBeenCalledWith(false);
    expect(remote).not.toHaveBeenCalled();
  });

  it("edits issue numbers in place", async () => {
    const onIssueNumberChange = vi.fn().mockResolvedValue(undefined);
    renderPanel({ onIssueNumberChange });
    await userEvent.click(
      await screen.findByRole("button", { name: "Edit issue numbers" }),
    );
    const input = screen.getByRole("textbox", { name: "Issue for v01.cbz" });
    await userEvent.clear(input);
    await userEvent.type(input, "7{Enter}");
    await waitFor(() =>
      expect(onIssueNumberChange).toHaveBeenCalledWith(
        expect.objectContaining({ impID: "a" }),
        "7",
      ),
    );
  });
});

describe("Import review tabs", () => {
  function serveQueue(seen: string[]) {
    server.use(
      http.get("/api/import", ({ request }) => {
        const url = new URL(request.url);
        seen.push(url.searchParams.get("bucket") ?? "");
        return HttpResponse.json({
          imports: [group()],
          pagination: { total: 1, limit: 50, offset: 0, has_more: false },
          summary: {
            group_count: 1,
            file_count: 2,
            buckets: { needs_pick: 5, confident: 18, ignored: 41 },
            confidence_bar: 80,
          },
        });
      }),
      http.post("/api/import/candidates", () => HttpResponse.json(panel())),
    );
  }

  it("counts each tab, asks for the tab picked, and points at the confident ones", async () => {
    const seen: string[] = [];
    serveQueue(seen);
    render(<ImportPage />);

    const tabs = await screen.findByRole("group", { name: "Review queue" });
    await waitFor(() =>
      expect(
        within(tabs).getByRole("button", { name: /Confident\s*18/ }),
      ).toBeTruthy(),
    );
    expect(
      screen.getByText(/18 more matched with high confidence/),
    ).toBeTruthy();
    await userEvent.click(
      within(tabs).getByRole("button", { name: /Ignored/ }),
    );
    await waitFor(() => expect(seen).toContain("ignored"));
    expect(seen[0]).toBe("needs_pick");
  });

  it("imports every confident match in one go", async () => {
    serveQueue([]);
    const confident = vi.fn(() =>
      HttpResponse.json({ groups: 18, imported: 40, failed: [] }),
    );
    server.use(http.post("/api/import/confident", confident));
    render(<ImportPage />);

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Import 18 confident matches",
      }),
    );
    await waitFor(() => expect(confident).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText("Imported 40 files from 18 confident matches"),
    ).toBeTruthy();
  });

  it("imports a group from the panel as the picked series", async () => {
    serveQueue([]);
    let sent: unknown = null;
    server.use(
      http.post("/api/import/match", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ success: true, matched: 2, imported: 2 });
      }),
    );
    render(<ImportPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Import as BLAME! (2016)" }),
    );
    await waitFor(() =>
      expect(sent).toMatchObject({
        imp_ids: ["a", "b"],
        comic_id: "cv-2016",
        add_missing: false,
      }),
    );
  });
});
