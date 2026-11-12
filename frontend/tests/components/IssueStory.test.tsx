import { beforeEach, describe, expect, it } from "vitest";
import { Route, Routes } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import IssueDetailPage from "@/pages/IssueDetailPage";

const issue = {
  IssueID: "iss-18",
  ComicID: "flash",
  ComicName: "Absolute Flash",
  Issue_Number: "18",
  IssueName: "Ascendant",
  ReleaseDate: "2026-08-19",
  Status: "Snatched",
};

const event = (
  id: number,
  created_at: string,
  activity: string,
  status: string,
  extra: Record<string, unknown> = {},
) => ({
  event_id: id,
  created_at,
  activity,
  status,
  subject_type: "issue",
  subject_id: "iss-18",
  subject_label: "Absolute Flash #18",
  parent_series_id: "flash",
  ...extra,
});

const cause = {
  cause_key: "sab_completed_file_not_found|failed",
  base_reason: "sab_completed_file_not_found",
  reason_phrase: "completed download file was not found",
  headline: "A finished download wasn't found on disk",
  hint: "Usually a path mapping between Comicarr and the client.",
  icon: "file",
  fix: { label: "Open path mappings", href: "/settings?section=clients" },
  stage: "failed",
  available_actions: ["retry", "search_again", "stop_wanting"],
  series_count: 1,
  member_count: 1,
  newest_updated_at: "2026-10-26 14:09:00",
  series: [],
  release_keys: ["rk-18"],
};

function renderIssue() {
  return render(
    <Routes>
      <Route
        path="/library/:comicId/issue/:issueId"
        element={<IssueDetailPage />}
      />
    </Routes>,
    { route: "/library/flash/issue/iss-18", useMemoryRouter: true },
  );
}

describe("Issue story", () => {
  let scopes: string[];
  let resolved: unknown[];

  beforeEach(() => {
    scopes = [];
    resolved = [];
    server.use(
      http.get("/api/metadata/issue/:issueId", () => HttpResponse.json(issue)),
      http.get("/api/series/flash", () =>
        HttpResponse.json({
          comic: { ComicID: "flash", ComicName: "Absolute Flash" },
          issues: [issue],
          annuals: [],
        }),
      ),
      http.get("/api/activity/timeline", ({ request }) => {
        scopes.push(new URL(request.url).search);
        const results = [
          event(3, "2026-10-26T14:09:00Z", "import", "failed", {
            reason_code: "sab_completed_file_not_found",
            reason_detail: "Looked in /downloads/complete",
          }),
          event(2, "2026-10-26T14:08:00Z", "download", "succeeded"),
          event(1, "2026-10-26T14:02:00Z", "grab", "succeeded", {
            provider: "NZBgeek",
          }),
        ];
        return HttpResponse.json({
          results,
          total: 3,
          limit: 25,
          offset: 0,
          has_more: false,
        });
      }),
      http.get("/api/attention", () =>
        HttpResponse.json({
          results: [],
          causes: [cause],
          total: 1,
          member_total: 1,
          preview_cap: 5,
        }),
      ),
      http.post("/api/attention/resolve", async ({ request }) => {
        resolved.push(await request.json());
        return HttpResponse.json({ success: true, results: [] });
      }),
    );
  });

  it("tells the issue's story oldest first, scoped to the issue", async () => {
    renderIssue();
    const steps = await screen.findAllByTestId("issue-story-step");
    expect(steps.map((s) => s.textContent)).toEqual([
      expect.stringContaining("Grabbed Absolute Flash #18 from NZBgeek"),
      expect.stringContaining("Downloaded Absolute Flash #18"),
      expect.stringContaining("Couldn't import Absolute Flash #18"),
    ]);
    // The server's own phrase replaces the generic "something went wrong".
    expect(steps[2].textContent).toContain(
      "Completed download file was not found",
    );
    expect(scopes[0]).toContain("scope_type=issue");
    expect(scopes[0]).toContain("scope_id=iss-18");
    expect(screen.getByTestId("issue-detail-title").textContent).toBe(
      "Absolute Flash #18",
    );
    expect(screen.getByText("Ascendant")).toBeTruthy();
  });

  it("names the likely cause and fixes it from the header", async () => {
    const user = userEvent.setup();
    renderIssue();

    const card = await screen.findByTestId("issue-likely-cause");
    expect(card.textContent).toContain(
      "Likely cause: A finished download wasn't found on disk",
    );
    expect(
      screen
        .getByRole("link", { name: "Open path mappings" })
        .getAttribute("href"),
    ).toBe("/settings?section=clients");
    expect(screen.getByTestId("issue-cause-line").textContent).toContain(
      "A finished download wasn't found on disk",
    );

    await user.click(screen.getByRole("button", { name: "Search again" }));
    expect(resolved).toEqual([
      { action: "search_again", release_keys: ["rk-18"] },
    ]);
  });

  it("says so when nothing has happened yet", async () => {
    server.use(
      http.get("/api/activity/timeline", () =>
        HttpResponse.json({
          results: [],
          total: 0,
          limit: 25,
          offset: 0,
          has_more: false,
        }),
      ),
      http.get("/api/attention", () =>
        HttpResponse.json({
          results: [],
          causes: [],
          total: 0,
          member_total: 0,
          preview_cap: 5,
        }),
      ),
    );
    renderIssue();
    expect(
      await screen.findByText(/Nothing has happened to this issue yet/),
    ).toBeTruthy();
    expect(screen.queryByTestId("issue-likely-cause")).toBeNull();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("imports a finished download by hand from the cause", async () => {
    server.use(
      http.get("/api/attention", () =>
        HttpResponse.json({
          results: [],
          causes: [
            {
              ...cause,
              stage: "manual_review",
              available_actions: ["import", "retry", "search_again"],
            },
          ],
          total: 1,
          member_total: 1,
          preview_cap: 5,
        }),
      ),
      http.get("/api/attention/import-source", () =>
        HttpResponse.json({
          release_key: "rk-18",
          nzb_name: "Absolute.Flash.018.2026.Digital",
          nzb_folder: "/data/usenet/complete/comics",
        }),
      ),
    );
    const user = userEvent.setup();
    renderIssue();

    const buttons = await screen.findAllByRole("button", {
      name: "Import manually",
    });
    await user.click(buttons[0]);
    const folder = await screen.findByLabelText("Folder");
    await screen.findByDisplayValue("/data/usenet/complete/comics");
    await user.clear(folder);
    await user.type(folder, "/mnt/comics");
    await user.click(screen.getByRole("button", { name: "Import" }));

    await screen.findByText(/Importing/);
    expect(resolved).toEqual([
      {
        action: "import",
        release_keys: ["rk-18"],
        import_source: {
          nzb_name: "Absolute.Flash.018.2026.Digital",
          nzb_folder: "/mnt/comics",
        },
      },
    ]);
  });

  it("summarises the last search under its step", async () => {
    server.use(
      http.get("/api/activity/timeline", () =>
        HttpResponse.json({
          results: [event(1, "2026-10-26T14:02:00Z", "search", "succeeded")],
          total: 1,
          limit: 25,
          offset: 0,
          has_more: false,
        }),
      ),
      http.get("/api/series/issues/:issueId/story", () =>
        HttpResponse.json({
          issue_id: "iss-18",
          attempts: { search: 1, grab: 0, download: 0, import: 0 },
          chosen: null,
          search: {
            total: 41,
            accepted_count: 3,
            rejected_count: 38,
            providers: [],
            searched_at: "2026-10-26T14:02:00Z",
            accepted: [],
            rejected: [],
            reasons: [
              {
                code: "rejected.issue_mismatch",
                label: "wrong issue",
                count: 21,
              },
              {
                code: "rejected.series_mismatch",
                label: "wrong series",
                count: 9,
              },
            ],
          },
          log: { query: "x", lines: [] },
        }),
      ),
    );
    renderIssue();
    const summary = await screen.findByTestId("issue-search-summary");
    expect(summary.textContent).toContain(
      "41 results, 38 rejected, 3 acceptable.",
    );
    expect(summary.textContent).toContain("21 wrong issue · 9 wrong series");
  });
});
