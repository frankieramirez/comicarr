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
});
