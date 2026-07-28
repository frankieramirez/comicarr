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
});
