import { beforeEach, describe, expect, it } from "vitest";
import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import SeriesDetailPage from "@/pages/SeriesDetailPage";

const canonicalIssues = [
  {
    IssueID: "unknown",
    ComicID: "1",
    Issue_Number: "1",
    IssueName: "Unverified copy",
    IssueDate: "2025-01-01",
    Status: "Skipped",
    displayState: "Unknown",
    acquisitionIntent: "policy",
    fulfillment: "unknown",
    missing: true,
    monitored: true,
    eligible: false,
    eligibilityReason: "unknown",
  },
  {
    IssueID: "failed",
    ComicID: "1",
    Issue_Number: "2",
    IssueName: "Failed transfer",
    IssueDate: "2025-02-01",
    Status: "Failed",
    displayState: "Failed",
    acquisitionIntent: "skipped",
    intentExplicit: true,
    fulfillment: "failed",
    missing: true,
    monitored: false,
    eligible: false,
    eligibilityReason: "explicit_skip",
  },
  {
    IssueID: "archived",
    ComicID: "1",
    Issue_Number: "3",
    IssueName: "Archived edition",
    IssueDate: "2025-03-01",
    Status: "Archived",
    displayState: "Archived",
    acquisitionIntent: "policy",
    fulfillment: "archived",
    owned: true,
    archived: true,
    monitored: true,
  },
  {
    IssueID: "reserved",
    ComicID: "1",
    Issue_Number: "4",
    IssueName: "Reserved handoff",
    IssueDate: "2025-04-01",
    Status: "Reserved",
    displayState: "Reserved",
    acquisitionIntent: "policy",
    fulfillment: "reserved",
    inFlight: true,
    monitored: true,
  },
  {
    IssueID: "snatched",
    ComicID: "1",
    Issue_Number: "5",
    IssueName: "Accepted handoff",
    IssueDate: "2025-05-01",
    Status: "Snatched",
    displayState: "Snatched",
    acquisitionIntent: "policy",
    fulfillment: "snatched",
    inFlight: true,
    monitored: true,
  },
  {
    IssueID: "ignored",
    ComicID: "1",
    Issue_Number: "6",
    IssueName: "Explicitly ignored",
    IssueDate: "2025-06-01",
    Status: "Ignored",
    displayState: "Ignored",
    acquisitionIntent: "ignored",
    intentExplicit: true,
    fulfillment: "missing",
    missing: true,
    monitored: false,
  },
  {
    IssueID: "skipped",
    ComicID: "1",
    Issue_Number: "7",
    IssueName: "Explicitly skipped",
    IssueDate: "2025-07-01",
    Status: "Skipped",
    displayState: "Skipped",
    acquisitionIntent: "skipped",
    intentExplicit: true,
    fulfillment: "missing",
    missing: true,
    monitored: false,
  },
  {
    IssueID: "wanted",
    ComicID: "1",
    Issue_Number: "8",
    IssueName: "Ready to search",
    IssueDate: "2025-08-01",
    Status: "Wanted",
    displayState: "Wanted",
    acquisitionIntent: "wanted",
    intentExplicit: true,
    fulfillment: "missing",
    missing: true,
    monitored: true,
    eligible: true,
  },
  {
    IssueID: "downloaded",
    ComicID: "1",
    Issue_Number: "9",
    IssueName: "Downloaded despite skip",
    IssueDate: "2025-09-01",
    Status: "Downloaded",
    displayState: "Downloaded",
    acquisitionIntent: "skipped",
    intentExplicit: true,
    fulfillment: "downloaded",
    owned: true,
    monitored: false,
  },
];

const annual = {
  IssueID: "annual-1",
  ComicID: "1",
  Issue_Number: "Annual 1",
  IssueName: "Annual event",
  IssueDate: "2025-10-01",
  Status: "Wanted",
  displayState: "Wanted",
  acquisitionIntent: "policy",
  fulfillment: "missing",
  missing: true,
  monitored: true,
  eligible: true,
  annual: true,
};

function renderDetail() {
  return render(
    <Routes>
      <Route path="/library/:comicId" element={<SeriesDetailPage />} />
    </Routes>,
    { route: "/library/1", useMemoryRouter: true },
  );
}

describe("SeriesDetailPage", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/series/1", () =>
        HttpResponse.json({
          comic: {
            ComicID: "1",
            ComicName: "Absolute Batman",
            ComicYear: "2024",
            ComicPublisher: "DC Comics",
            Status: "Active",
            Have: 999,
            Total: 999,
          },
          issues: canonicalIssues,
          annuals: [annual],
          providerLinks: [
            {
              provider: "comicvine",
              label: "ComicVine",
              url: "https://comicvine.gamespot.com/volume/4050-1/",
            },
          ],
          summary: {
            total: 10,
            issues: 9,
            annuals: 1,
            owned: 2,
            archived: 1,
            inFlight: 2,
            missing: 6,
            monitored: 6,
            wanted: 2,
            skipped: 3,
            ignored: 1,
            failed: 1,
            unknown: 1,
            eligible: 2,
            completionPercent: 20,
          },
        }),
      ),
    );
  });

  it("shows last sync from LastUpdated and renders the description", async () => {
    server.use(
      http.get("/api/series/1", () =>
        HttpResponse.json({
          comic: {
            ComicID: "md-synced",
            ComicName: "One Piece",
            Status: "Active",
            LatestDate: "Unknown",
            LastUpdated: "2026-08-16 12:00:00",
            Description: "Pirates hunt the One Piece.",
          },
          issues: canonicalIssues,
          annuals: [],
          summary: { total: 0, owned: 0, missing: 0 },
        }),
      ),
    );
    renderDetail();
    expect(
      await screen.findByText(/last sync 2026-08-16 12:00:00/),
    ).toBeTruthy();
    expect(screen.getByText("Pirates hunt the One Piece.")).toBeTruthy();
    expect(screen.queryByText("unsynced")).toBeNull();
  });

  it("still reads unsynced when no refresh timestamp exists", async () => {
    server.use(
      http.get("/api/series/1", () =>
        HttpResponse.json({
          comic: {
            ComicID: "mal-unsynced",
            ComicName: "Akira",
            Status: "Active",
            LatestDate: "Unknown",
            LastUpdated: null,
          },
          issues: canonicalIssues,
          annuals: [],
          summary: { total: 0, owned: 0, missing: 0 },
        }),
      ),
    );
    renderDetail();
    expect(await screen.findByText(/unsynced/)).toBeTruthy();
    expect(screen.queryByText(/last sync/)).toBeNull();
  });

  it("loads the cover from the art proxy, never a MangaDex hotlink", async () => {
    server.use(
      http.get("/api/series/1", () =>
        HttpResponse.json({
          comic: {
            ComicID: "md-onepiece",
            ComicName: "One Piece",
            Status: "Active",
            ComicImage: "https://uploads.mangadex.org/covers/uuid/cover.jpg",
            ComicImageURL: "https://uploads.mangadex.org/covers/uuid/cover.jpg",
          },
          issues: canonicalIssues,
          annuals: [],
          summary: { total: 0, owned: 0, missing: 0 },
        }),
      ),
    );
    renderDetail();
    const cover = await screen.findByRole("img", { name: "One Piece" });
    expect(cover.getAttribute("src")).toBe("/api/metadata/art/md-onepiece");
    expect(cover.getAttribute("src")).not.toContain("uploads.mangadex.org");
  });

  it("links out to the series page on its metadata provider", async () => {
    renderDetail();
    const link = await screen.findByRole("link", { name: "View on ComicVine" });
    expect(link.getAttribute("href")).toBe(
      "https://comicvine.gamespot.com/volume/4050-1/",
    );
    expect(link.getAttribute("target")).toBe("_blank");
  });

  it("shows MyAnimeList and MangaDex when both ids exist", async () => {
    server.use(
      http.get("/api/series/1", () =>
        HttpResponse.json({
          comic: {
            ComicID: "mal-161890",
            ComicName: "Absolute Batman",
            Status: "Active",
          },
          issues: canonicalIssues,
          providerLinks: [
            {
              provider: "myanimelist",
              label: "MyAnimeList",
              url: "https://myanimelist.net/manga/161890",
            },
            {
              provider: "mangadex",
              label: "MangaDex",
              url: "https://mangadex.org/title/uuid-2",
            },
          ],
        }),
      ),
    );
    renderDetail();
    expect(
      (
        await screen.findByRole("link", { name: "View on MyAnimeList" })
      ).getAttribute("href"),
    ).toBe("https://myanimelist.net/manga/161890");
    expect(
      screen
        .getByRole("link", { name: "View on MangaDex" })
        .getAttribute("href"),
    ).toBe("https://mangadex.org/title/uuid-2");
  });

  it("deep-links to scoped Activity without embedding a feed", async () => {
    renderDetail();
    await screen.findByText("Absolute Batman");

    const activityLink = screen.getByRole("link", {
      name: "View activity for this series",
    });
    expect(activityLink.getAttribute("href")).toBe(
      "/activity?scope_type=series&scope_id=1",
    );
    // No embedded timeline feed on the detail page.
    expect(screen.queryByLabelText("Activity timeline")).toBeNull();
    expect(screen.queryByLabelText("Needs attention")).toBeNull();
  });

  it("persists a provider-independent content kind and refreshes the series", async () => {
    let contentType = "comic";
    let payload: unknown;
    let detailReads = 0;
    server.use(
      http.get("/api/series/1", () => {
        detailReads += 1;
        return HttpResponse.json({
          comic: {
            ComicID: "1",
            ComicName: "Absolute Batman",
            ComicYear: "2024",
            ComicPublisher: "DC Comics",
            Status: "Active",
            ContentType: contentType,
          },
          issues: canonicalIssues,
          annuals: [annual],
        });
      }),
      http.patch("/api/series/1/content-kind", async ({ request }) => {
        payload = await request.json();
        contentType = "manga";
        return HttpResponse.json({ success: true, content_type: "manga" });
      }),
    );
    const user = userEvent.setup();
    renderDetail();

    expect(
      await screen.findByText(/Metadata still comes from ComicVine/),
    ).toBeTruthy();
    expect(
      screen.getByText(/Existing files and issue history stay unchanged/),
    ).toBeTruthy();
    screen.getByRole("radio", { name: "Comic" }).focus();
    await user.keyboard("{ArrowRight}");

    await waitFor(() => expect(payload).toEqual({ content_type: "manga" }));
    await waitFor(() => expect(detailReads).toBeGreaterThan(1));
    expect(await screen.findByText("Content kind updated")).toBeTruthy();
    expect(
      screen.getByRole("radio", { name: "Manga" }).getAttribute("aria-checked"),
    ).toBe("true");
    expect(screen.getByText(/Use manga chapter labels/)).toBeTruthy();
  });

  it("keeps the current kind and reports an API failure", async () => {
    server.use(
      http.patch("/api/series/1/content-kind", () =>
        HttpResponse.json({ detail: "save failed" }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderDetail();

    await user.click(await screen.findByRole("radio", { name: "Manga" }));

    expect(await screen.findByText("Content kind not updated")).toBeTruthy();
    expect(
      screen.getByRole("radio", { name: "Comic" }).getAttribute("aria-checked"),
    ).toBe("true");
  });

  it("uses the canonical summary and shows annuals, evidence, and intent separately", async () => {
    const user = userEvent.setup();
    renderDetail();

    await screen.findByText("Absolute Batman");

    expect(screen.getByText("20%")).toBeTruthy();
    expect(screen.getByRole("button", { name: "All 10" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Have 2" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Missing 6" })).toBeTruthy();
    expect(screen.getByText(/annuals: 1/)).toBeTruthy();
    expect(screen.getByText("Annual")).toBeTruthy();

    for (const state of [
      "Unknown",
      "Failed",
      "Archived",
      "Reserved",
      "Snatched",
      "Ignored",
      "Skipped",
      "Wanted",
      "Downloaded",
    ]) {
      expect(screen.getAllByText(state).length).toBeGreaterThan(0);
    }
    expect(screen.getAllByText("intent: skipped").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Missing 6" }));
    expect(screen.getByText("Unverified copy")).toBeTruthy();
    expect(screen.getByText("Annual event")).toBeTruthy();
    expect(screen.queryByText("Archived edition")).toBeNull();
    expect(screen.queryByText("Reserved handoff")).toBeNull();
  });

  it("renders sentinel/null/empty issue dates as — and keeps valid ISO dates", async () => {
    server.use(
      http.get("/api/series/1", () =>
        HttpResponse.json({
          comic: {
            ComicID: "1",
            ComicName: "Date Edge Cases",
            ComicYear: "2024",
            ComicPublisher: "DC Comics",
            Status: "Active",
            Have: 0,
            Total: 4,
          },
          issues: [
            {
              IssueID: "sentinel",
              ComicID: "1",
              Issue_Number: "1",
              IssueName: "Sentinel release",
              releaseDate: "0000-00-00",
              issueDate: "0000-00-00",
              Status: "Wanted",
              displayState: "Wanted",
              missing: true,
              monitored: true,
            },
            {
              IssueID: "null-date",
              ComicID: "1",
              Issue_Number: "2",
              IssueName: "Null dates",
              releaseDate: null,
              issueDate: null,
              Status: "Wanted",
              displayState: "Wanted",
              missing: true,
              monitored: true,
            },
            {
              IssueID: "empty-date",
              ComicID: "1",
              Issue_Number: "3",
              IssueName: "Empty dates",
              releaseDate: "",
              issueDate: "",
              Status: "Wanted",
              displayState: "Wanted",
              missing: true,
              monitored: true,
            },
            {
              IssueID: "valid-fallback",
              ComicID: "1",
              Issue_Number: "4",
              IssueName: "Valid cover date",
              releaseDate: "0000-00-00",
              issueDate: "2025-08-15",
              Status: "Wanted",
              displayState: "Wanted",
              missing: true,
              monitored: true,
            },
          ],
          annuals: [],
          summary: {
            total: 4,
            issues: 4,
            annuals: 0,
            owned: 0,
            archived: 0,
            inFlight: 0,
            missing: 4,
            monitored: 4,
            wanted: 4,
            skipped: 0,
            ignored: 0,
            failed: 0,
            unknown: 0,
            eligible: 4,
            completionPercent: 0,
          },
        }),
      ),
    );

    renderDetail();

    await screen.findByText("Date Edge Cases");
    expect(screen.getByText("Sentinel release")).toBeTruthy();
    expect(screen.getByText("Valid cover date")).toBeTruthy();
    expect(screen.getByText("2025-08-15")).toBeTruthy();
    expect(screen.queryByText("0000-00-00")).toBeNull();
    // Three unknown rows share the em dash placeholder used elsewhere on the page.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });

  it("previews once, requires confirmation, and follows the accepted durable run", async () => {
    let confirmationPayload: unknown;
    server.use(
      http.get("/api/series/1/search-missing/preview", () =>
        HttpResponse.json({
          success: true,
          comicId: "1",
          eligibleCount: 2,
          excludedCount: 8,
          eligible: [
            { issueId: "wanted", issueNumber: "8", entityType: "issue" },
            {
              issueId: "annual-1",
              issueNumber: "Annual 1",
              entityType: "annual",
            },
          ],
          excluded: [],
          route: { viable: true },
          canSearch: true,
          preview_token: "preview-token",
          fingerprint: "preview-fingerprint",
        }),
      ),
      http.post("/api/series/1/search-missing", async ({ request }) => {
        confirmationPayload = await request.json();
        return HttpResponse.json({
          success: true,
          status: "accepted",
          accepted: 2,
          rejected: 8,
          run_id: "run-1",
          message: "Queued 2 missing issue(s) for search",
        });
      }),
      http.get("/api/search/runs/run-1", () =>
        HttpResponse.json({
          success: true,
          run: {
            run_id: "run-1",
            command_kind: "search",
            trigger: "series_bulk",
            scope_type: "series",
            scope_id: "1",
            dispatch_state: "accepted",
            completion_state: "completed",
            accepted_count: 2,
            terminal_count: 2,
            succeeded_count: 1,
            no_match_count: 1,
            blocked_count: 0,
            failed_count: 0,
            created_at: "2026-07-11T00:00:00Z",
            updated_at: "2026-07-11T00:00:01Z",
            completed_at: "2026-07-11T00:00:01Z",
          },
          items: [],
        }),
      ),
    );

    const user = userEvent.setup();
    renderDetail();

    await user.click(
      await screen.findByRole("button", { name: "Search all missing" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Search missing issues" }),
    ).toBeTruthy();
    expect(
      screen.getByText("2 eligible issues will be searched."),
    ).toBeTruthy();
    expect(
      screen.getByText("8 issues are excluded from this run."),
    ).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Confirm search" }));

    await waitFor(() => {
      expect(confirmationPayload).toEqual({
        confirm: true,
        preview_token: "preview-token",
        fingerprint: "preview-fingerprint",
      });
    });
    expect(await screen.findByText("Search run accepted")).toBeTruthy();
    expect(await screen.findByText("completed")).toBeTruthy();
    expect(screen.getByText("1 matched · 1 no match")).toBeTruthy();
  });

  it("explains how to recover when no safe route is ready", async () => {
    server.use(
      http.get("/api/series/1/search-missing/preview", () =>
        HttpResponse.json({
          success: true,
          comicId: "1",
          eligibleCount: 2,
          excludedCount: 8,
          route: { viable: false, reason: "path_not_ready" },
          canSearch: false,
        }),
      ),
    );

    const user = userEvent.setup();
    renderDetail();

    await user.click(
      await screen.findByRole("button", { name: "Search all missing" }),
    );

    expect(
      await screen.findByText("Search configuration needs attention"),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "The configured download directory does not exist on the server. Check the path and any container mounts.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("path_not_ready")).toBeTruthy();
    expect(
      screen
        .getByRole("button", { name: "Confirm search" })
        .hasAttribute("disabled"),
    ).toBe(true);
  });

  it("links a missing provider blocker to search provider settings", async () => {
    server.use(
      http.get("/api/series/1/search-missing/preview", () =>
        HttpResponse.json({
          success: true,
          comicId: "1",
          eligibleCount: 2,
          excludedCount: 8,
          route: { viable: false, reason: "provider_not_configured" },
          canSearch: false,
        }),
      ),
    );

    const user = userEvent.setup();
    renderDetail();

    await user.click(
      await screen.findByRole("button", { name: "Search all missing" }),
    );

    expect(
      await screen.findByText(
        "No Usenet indexer is configured. Add and enable one in Search settings.",
      ),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Open search settings" })
        .getAttribute("href"),
    ).toBe("/settings?section=search");
  });

  it("starts Interactive Search for a series issue in place", async () => {
    let searchBody: unknown;
    server.use(
      http.post("/api/search/interactive", async ({ request }) => {
        searchBody = await request.json();
        return HttpResponse.json({
          session_id: "session-issue",
          entity_type: "issue",
          entity_id: "wanted",
          series_id: "1",
          state: "complete",
          candidate_count: 0,
          progress: {
            provider_total: 0,
            provider_completed: 0,
            current_provider: null,
          },
          provider_failures: [],
          created_at: "2026-08-12T04:00:00Z",
          expires_at: "2026-08-12T04:10:00Z",
          candidates: [],
        });
      }),
    );
    const user = userEvent.setup();
    renderDetail();

    await screen.findByText("Ready to search");
    await user.click(
      screen.getByRole("button", {
        name: "Interactive Search for Ready to search",
      }),
    );

    await waitFor(() => {
      expect(searchBody).toEqual({
        entity_type: "issue",
        entity_id: "wanted",
      });
    });
    expect(
      await screen.findByRole("heading", { name: "Review releases" }),
    ).toBeTruthy();
  });

  it("starts Interactive Search for an annual in place", async () => {
    let searchBody: unknown;
    server.use(
      http.post("/api/search/interactive", async ({ request }) => {
        searchBody = await request.json();
        return HttpResponse.json({
          session_id: "session-annual",
          entity_type: "annual",
          entity_id: "annual-1",
          series_id: "1",
          state: "complete",
          candidate_count: 0,
          progress: {
            provider_total: 0,
            provider_completed: 0,
            current_provider: null,
          },
          provider_failures: [],
          created_at: "2026-08-12T04:00:00Z",
          expires_at: "2026-08-12T04:10:00Z",
          candidates: [],
        });
      }),
    );
    const user = userEvent.setup();
    renderDetail();

    await screen.findByText("Annual event");
    await user.click(
      screen.getByRole("button", {
        name: "Interactive Search for Annual event",
      }),
    );

    await waitFor(() => {
      expect(searchBody).toEqual({
        entity_type: "annual",
        entity_id: "annual-1",
      });
    });
    expect(
      await screen.findByRole("heading", { name: "Review releases" }),
    ).toBeTruthy();
  });
});
