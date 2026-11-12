import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen, within } from "../test-utils";
import ReleasesPage from "@/pages/ReleasesPage";
import { landedLabel, releaseNumber, releaseState } from "@/lib/releaseState";
import type { UpcomingIssue } from "@/types";

const issue = (overrides: Partial<UpcomingIssue>): UpcomingIssue =>
  ({
    IssueID: "i-1",
    ComicID: "c-1",
    ComicName: "Absolute Batman",
    IssueNumber: "23",
    IssueDate: "2026-10-14",
    Status: "Wanted",
    Publisher: "DC Comics",
    ContentType: "comic",
    attention: null,
    ...overrides,
  }) as UpcomingIssue;

const WEEK = {
  week: "41",
  year: "2026",
  start: "2026-10-11",
  end: "2026-10-17",
  offset: 0,
  prev: { week: "40", year: "2026" },
  next: { week: "42", year: "2026" },
  source: "stored",
  rows: [],
};

function serveWeek(rows: UpcomingIssue[], seen: string[] = []) {
  server.use(
    http.get("/api/weekly", () => HttpResponse.json(WEEK)),
    http.get("/api/upcoming", ({ request }) => {
      const url = new URL(request.url);
      seen.push(url.search);
      return HttpResponse.json(rows);
    }),
  );
}

const ROWS = [
  issue({
    IssueID: "dl",
    ComicName: "Dandadan",
    IssueNumber: "213",
    IssueDate: "2026-10-13",
    Status: "Downloaded",
    Publisher: "Shueisha",
    ContentType: "manga",
  }),
  issue({
    IssueID: "fail",
    ComicName: "Absolute Wonder Woman",
    attention: "Import failed",
  }),
  issue({ IssueID: "snatch", ComicName: "Absolute Flash", Status: "Snatched" }),
  issue({ IssueID: "later", ComicName: "Ark-M", IssueDate: "2099-01-02" }),
];

describe("Releases > Mine by day", () => {
  it("groups the week under one heading per release day", async () => {
    serveWeek(ROWS);
    render(<ReleasesPage />, { useMemoryRouter: true, route: "/releases" });

    await screen.findByText("Dandadan");
    const groups = screen.getAllByTestId("release-day-group");
    expect(groups.map((g) => g.textContent)).toEqual([
      "Tuesday, Oct 131",
      "Wednesday, Oct 142New comic day",
      "Friday, Jan 21",
    ]);
    expect(screen.getByText("Ch. 213")).toBeTruthy();
  });

  it("counts and filters by where each release stands", async () => {
    serveWeek(ROWS);
    const user = userEvent.setup();
    render(<ReleasesPage />, { useMemoryRouter: true, route: "/releases" });
    await screen.findByText("Dandadan");

    const tabs = screen.getByRole("group", { name: "Where it stands" });
    expect(
      [...tabs.querySelectorAll("button")].map((b) => b.textContent),
    ).toEqual([
      "All4",
      "Needs you1",
      "In progress1",
      "Downloaded1",
      "Coming up1",
    ]);

    await user.click(within(tabs).getByRole("button", { name: /^Needs you/ }));
    expect(screen.getByText("Absolute Wonder Woman")).toBeTruthy();
    expect(screen.queryByText("Dandadan")).toBeNull();
    expect(screen.getByText("Import failed")).toBeTruthy();
    expect(screen.getByRole("link", { name: "· see why" })).toBeTruthy();
  });

  it("filters by series or publisher", async () => {
    serveWeek(ROWS);
    const user = userEvent.setup();
    render(<ReleasesPage />, { useMemoryRouter: true, route: "/releases" });
    await screen.findByText("Dandadan");

    await user.type(screen.getByLabelText("Filter releases"), "shueisha");
    expect(screen.getByText("Dandadan")).toBeTruthy();
    expect(screen.queryByText("Absolute Flash")).toBeNull();
  });

  it("asks for the week the header shows", async () => {
    const seen: string[] = [];
    serveWeek(ROWS, seen);
    render(<ReleasesPage />, {
      useMemoryRouter: true,
      route: "/releases?view=mine&week=42&year=2026",
    });
    await screen.findByText("Dandadan");
    expect(seen).toContain("?include_downloaded_issues=true&week=42&year=2026");
  });
});

describe("releaseState", () => {
  const today = "2026-10-14";

  it("puts Needs attention ahead of the issue's own status", () => {
    expect(
      releaseState(
        issue({ Status: "Downloaded", attention: "Import failed" }),
        today,
      ).bucket,
    ).toBe("needs_you");
  });

  it("splits Wanted into searching now and coming up", () => {
    expect(releaseState(issue({}), today)).toMatchObject({
      bucket: "in_progress",
      label: "Searching",
    });
    expect(
      releaseState(issue({ IssueDate: "2026-10-16" }), today),
    ).toMatchObject({ bucket: "coming_up", label: "Out Friday" });
  });

  it("numbers manga by chapter", () => {
    expect(
      releaseNumber(issue({ ContentType: "manga", IssueNumber: "5" })),
    ).toBe("Ch. 5");
    expect(releaseNumber(issue({}))).toBe("#23");
  });

  it("says how far a download is and when a finished one landed", () => {
    const now = new Date("2026-10-14T15:00:00");
    const downloading = releaseState(
      issue({
        Status: "Snatched",
        download: { phase: "downloading", percent: 64, time_left: null },
      }),
      "2026-10-14",
    );
    expect(downloading).toMatchObject({ label: "Downloading", progress: 64 });
    expect(
      releaseState(
        issue({
          Status: "Snatched",
          download: { phase: "importing", percent: null, time_left: null },
        }),
        "2026-10-14",
      ).label,
    ).toBe("Importing");
    expect(landedLabel("2026-10-14T13:00:00", now)).toBe("2h ago");
    expect(landedLabel("2026-10-13T09:00:00", now)).toBe("yesterday");
    expect(landedLabel("2026-10-11T21:40:00", now)).toBe("Sun 21:40");
    expect(landedLabel(null, now)).toBeUndefined();
  });

  it("shows download progress and the cause's fix on its row", async () => {
    serveWeek([
      issue({
        IssueID: "snatch",
        ComicName: "Absolute Flash",
        Status: "Snatched",
        download: { phase: "downloading", percent: 64, time_left: null },
      }),
      issue({
        IssueID: "fail",
        ComicName: "Absolute Wonder Woman",
        attention: "Import failed",
        attention_reason: "invalid_postprocess_command",
      }),
    ]);
    server.use(
      http.get("/api/attention", () =>
        HttpResponse.json({
          results: [],
          causes: [
            {
              cause_key: "invalid_postprocess_command|failed",
              base_reason: "invalid_postprocess_command",
              reason_phrase: "post-processing command is invalid",
              headline: "Post-processing is misconfigured",
              hint: null,
              icon: "settings",
              fix: {
                label: "Open post-processing",
                href: "/settings?section=media",
              },
              stage: "failed",
              available_actions: ["retry"],
              series_count: 1,
              member_count: 1,
              newest_updated_at: "2026-10-14 09:00:00",
              series: [],
              release_keys: ["rk"],
            },
          ],
          total: 1,
          member_total: 1,
          preview_cap: 5,
        }),
      ),
    );
    render(<ReleasesPage />, { useMemoryRouter: true, route: "/releases" });

    const bar = await screen.findByRole("progressbar", {
      name: "Downloading 64%",
    });
    expect(bar.getAttribute("aria-valuenow")).toBe("64");
    const fix = await screen.findByRole("link", {
      name: "Open post-processing",
    });
    expect(fix.getAttribute("href")).toBe("/settings?section=media");
    expect(
      screen.getByRole("link", { name: "· see why" }).getAttribute("href"),
    ).toBe("/library/c-1/issue/fail");
  });
});
