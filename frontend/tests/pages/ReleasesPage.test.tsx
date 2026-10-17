import { describe, expect, it } from "vitest";
import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen } from "../test-utils";
import ReleasesPage from "@/pages/ReleasesPage";
import { weeklyReleaseRowKey } from "@/pages/weeklyReleaseRowKey";

describe("ReleasesPage", () => {
  const upcomingIssue = {
    IssueID: "issue-19",
    ComicID: "comic-1",
    ComicName: "Absolute Batman",
    IssueNumber: "19",
    Issue_Number: "19",
    IssueDate: "2026-08-12",
    Status: "Wanted",
  };

  it("queues a weekly refresh and reports its accepted state", async () => {
    const user = userEvent.setup();
    render(<ReleasesPage />);

    await user.click(
      await screen.findByRole("button", { name: "Refresh releases" }),
    );

    await waitFor(() => {
      expect(
        screen.getByText("Refresh queued — it will start shortly."),
      ).toBeTruthy();
    });
  });

  it("explains when the scheduler is paused instead of claiming a queued refresh", async () => {
    server.use(
      http.post("/api/weekly/refresh", () =>
        HttpResponse.json({
          accepted: false,
          state: "paused",
          error: "Weekly refresh is paused",
        }),
      ),
    );
    const user = userEvent.setup();
    render(<ReleasesPage />);

    await user.click(
      await screen.findByRole("button", { name: "Refresh releases" }),
    );

    expect(await screen.findByText("Weekly refresh is paused")).toBeTruthy();
    expect(
      screen.queryByText("Refresh queued — it will start shortly."),
    ).toBeNull();
  });

  it("still asks the operator to fix the connection on a generic pull failure", async () => {
    server.use(
      http.get("/api/system/jobs", () =>
        HttpResponse.json({
          jobs: [
            {
              id: "weekly",
              name: "Weekly Pullist",
              next_run_time: "2026-07-12T00:00:00Z",
              trigger: "interval",
              status: "Error",
              last_success_timestamp: null,
              last_failure_timestamp: Date.now() / 1_000,
              last_error: "Weekly pull source reported a failure",
            },
          ],
        }),
      ),
    );
    const user = userEvent.setup();
    render(<ReleasesPage />);

    await user.click(
      await screen.findByRole("button", { name: "Refresh releases" }),
    );

    expect(
      await screen.findByText(/fixing the pull source connection/i),
    ).toBeTruthy();
  });

  it("names an upstream Walksoftly outage instead of a local connection to fix", async () => {
    server.use(
      http.get("/api/system/jobs", () =>
        HttpResponse.json({
          jobs: [
            {
              id: "weekly",
              name: "Weekly Pullist",
              next_run_time: "2026-07-12T00:00:00Z",
              trigger: "interval",
              status: "Error",
              last_success_timestamp: null,
              last_failure_timestamp: Date.now() / 1_000,
              last_error:
                "Walksoftly is unreachable. The pull-list source is down upstream.",
            },
          ],
        }),
      ),
    );
    const user = userEvent.setup();
    render(<ReleasesPage />);

    await user.click(
      await screen.findByRole("button", { name: "Refresh releases" }),
    );

    expect(await screen.findByText(/Walksoftly is unreachable/i)).toBeTruthy();
    expect(screen.queryByText(/fixing the pull source connection/i)).toBeNull();
  });

  it("reports a refresh that finishes before the accepted response is rendered", async () => {
    server.use(
      http.get("/api/system/jobs", () =>
        HttpResponse.json({
          jobs: [
            {
              id: "weekly",
              name: "Weekly Pullist",
              next_run_time: "2026-07-12T00:00:00Z",
              trigger: "interval",
              status: "Waiting",
              last_success_timestamp: Date.now() / 1_000,
              last_failure_timestamp: null,
              last_error: null,
            },
          ],
        }),
      ),
    );
    const user = userEvent.setup();
    render(<ReleasesPage />);

    await user.click(
      await screen.findByRole("button", { name: "Refresh releases" }),
    );

    expect(await screen.findByText("Releases refreshed.")).toBeTruthy();
  });

  const weeklyRow = (overrides: Record<string, unknown> = {}) => ({
    COMIC: "Absolute Batman",
    ISSUE: "19",
    PUBLISHER: "DC",
    SHIPDATE: "2026-08-12",
    STATUS: "Skipped",
    ComicID: "comic-1",
    IssueID: "issue-19",
    rowid: 1,
    in_library: true,
    library_issue_id: "issue-19",
    issue_status: "Wanted",
    state: "wanted",
    ...overrides,
  });

  const weeklyWeek = (
    rows: unknown[],
    overrides: Record<string, unknown> = {},
  ) => ({
    week: "41",
    year: "2026",
    start: "2026-10-11",
    end: "2026-10-17",
    offset: 0,
    prev: { week: "40", year: "2026" },
    next: { week: "42", year: "2026" },
    source: "stored",
    rows,
    ...overrides,
  });

  const renderIndustry = (route = "/releases?view=all") =>
    render(<ReleasesPage />, { useMemoryRouter: true, route });

  it("uses a phone weekly grid that keeps title, status, and actions", async () => {
    server.use(
      http.get("/api/weekly", () =>
        HttpResponse.json(weeklyWeek([weeklyRow()])),
      ),
    );
    renderIndustry();

    const row = await screen.findByTestId("weekly-release-row");
    expect(row.className).toMatch(/grid-cols-\[minmax\(0,1fr\)_auto_auto\]/);
    expect(row.className).toMatch(
      /md:grid-cols-\[minmax\(0,1fr\)_80px_160px_110px_120px\]/,
    );
    expect(row.querySelectorAll(".max-md\\:hidden").length).toBeGreaterThan(0);
    const phoneId = screen.getByTestId("phone-row-id");
    expect(phoneId.textContent).toContain("#19");
    expect(phoneId.className).toMatch(/hidden/);
    expect(phoneId.className).toMatch(/max-md:inline/);
  });

  it("steps to the next week and back to this week", async () => {
    const requested: string[] = [];
    server.use(
      http.get("/api/weekly", ({ request }) => {
        const url = new URL(request.url);
        const week = url.searchParams.get("week");
        requested.push(week ?? "current");
        return HttpResponse.json(
          week === "42"
            ? weeklyWeek([weeklyRow({ COMIC: "Next Week Book" })], {
                week: "42",
                start: "2026-10-18",
                end: "2026-10-24",
                offset: 1,
                prev: { week: "41", year: "2026" },
                next: { week: "43", year: "2026" },
              })
            : weeklyWeek([weeklyRow()]),
        );
      }),
    );
    const user = userEvent.setup();
    renderIndustry();

    expect(await screen.findByText("This week")).toBeTruthy();
    expect(screen.getByText("Oct 11 – Oct 17, 2026")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Next week" }));

    expect(await screen.findByText("Next Week Book")).toBeTruthy();
    expect(screen.getByText("Oct 18 – Oct 24, 2026")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "This week" }));

    expect(await screen.findByText("Absolute Batman")).toBeTruthy();
    expect(requested.slice(0, 2)).toEqual(["current", "42"]);
  });

  it("disables next at the edge of the browsable window", async () => {
    server.use(
      http.get("/api/weekly", () =>
        HttpResponse.json(weeklyWeek([weeklyRow()], { offset: 4, next: null })),
      ),
    );
    renderIndustry("/releases?view=all&week=45&year=2026");

    const next = await screen.findByRole("button", { name: "Next week" });
    await waitFor(() => expect(next.hasAttribute("disabled")).toBe(true));
    expect(screen.getByText("In 4 weeks")).toBeTruthy();
  });

  it("filters and sorts the week, and counts each library state", async () => {
    server.use(
      http.get("/api/weekly", () =>
        HttpResponse.json(
          weeklyWeek([
            weeklyRow({ COMIC: "Zorro", PUBLISHER: "Dynamite", rowid: 1 }),
            weeklyRow({
              COMIC: "Amazing Spider-Man",
              PUBLISHER: "Marvel",
              ISSUE: "2",
              rowid: 2,
              state: "not_in_library",
              in_library: false,
            }),
            weeklyRow({
              COMIC: "Batman",
              PUBLISHER: "Aftershock",
              ISSUE: "1",
              rowid: 3,
              state: "downloaded",
            }),
          ]),
        ),
      ),
    );
    const user = userEvent.setup();
    renderIndustry();

    await screen.findByText("Zorro");
    const titles = () =>
      screen
        .getAllByTestId("weekly-release-row")
        .map((row) => row.querySelector("[data-grid-title]")?.textContent);
    expect(titles()[0]).toContain("Amazing Spider-Man");

    await user.click(screen.getByRole("button", { name: "publisher" }));
    expect(titles()[0]).toContain("Batman");

    await user.type(screen.getByLabelText("Filter releases"), "marvel");
    expect(titles()).toHaveLength(1);
    expect(titles()[0]).toContain("Amazing Spider-Man");

    const legend = screen.getByTestId("weekly-legend");
    expect(legend.textContent).toContain("Wanted 1");
    expect(legend.textContent).toContain("Downloaded 1");
    expect(legend.textContent).toContain("Not in library 1");
  });

  it("adds a series from the pull list and wants that issue", async () => {
    const posted: unknown[] = [];
    server.use(
      http.get("/api/weekly", () =>
        HttpResponse.json(
          weeklyWeek([
            weeklyRow({
              rowid: 7,
              state: "not_in_library",
              in_library: false,
              library_issue_id: null,
            }),
          ]),
        ),
      ),
      http.post("/api/weekly/add", async ({ request }) => {
        posted.push(await request.json());
        return HttpResponse.json({
          success: true,
          comicid: "comic-1",
          want_queued: true,
        });
      }),
    );
    const user = userEvent.setup();
    renderIndustry();

    await user.click(
      await screen.findByRole("button", { name: "Add Absolute Batman" }),
    );
    await user.click(
      await screen.findByRole("menuitem", {
        name: "Add series and want #19",
      }),
    );

    expect(await screen.findByText("adding…")).toBeTruthy();
    expect(posted).toEqual([{ rowid: 7, want: true }]);
  });

  it("wants an issue of a series already in the library", async () => {
    const queued: string[] = [];
    server.use(
      http.get("/api/weekly", () =>
        HttpResponse.json(
          weeklyWeek([
            weeklyRow({ state: "in_library", issue_status: "Skipped" }),
          ]),
        ),
      ),
      http.put("/api/series/issues/:issueId/queue", ({ params }) => {
        queued.push(String(params.issueId));
        return HttpResponse.json({ success: true });
      }),
    );
    const user = userEvent.setup();
    renderIndustry();

    await user.click(
      await screen.findByRole("button", { name: "Want Absolute Batman #19" }),
    );

    await waitFor(() => expect(queued).toEqual(["issue-19"]));
    const link = screen.getByRole("link", { name: "Absolute Batman" });
    expect(link.getAttribute("href")).toBe("/library/comic-1");
  });

  it("explains a week no source has filled yet", async () => {
    server.use(
      http.get("/api/weekly", () =>
        HttpResponse.json(weeklyWeek([], { source: "unavailable", offset: 3 })),
      ),
    );
    renderIndustry();

    expect(
      await screen.findByText(/Neither Walksoftly nor ComicVine has this week/),
    ).toBeTruthy();
  });

  it("keeps weekly row keys unique when ComicID is missing", () => {
    const duplicate = {
      COMIC: "Batman",
      ISSUE: "1",
      PUBLISHER: "DC",
      SHIPDATE: "2026-08-12",
      STATUS: "Available",
      ComicID: null,
      IssueID: null,
    };
    expect(weeklyReleaseRowKey(duplicate, 0)).not.toEqual(
      weeklyReleaseRowKey(duplicate, 1),
    );
  });

  it("paints Wanted rows with --status-wanted", async () => {
    server.use(
      http.get("/api/upcoming", () => HttpResponse.json([upcomingIssue])),
    );
    const { container } = render(<ReleasesPage />);
    await screen.findByText("Absolute Batman");
    const style = container
      .querySelector('[data-testid="status-dot"]')
      ?.getAttribute("style");
    expect(style).toContain("var(--status-wanted)");
  });

  it("offers interactive review for wanted releases", async () => {
    server.use(
      http.get("/api/upcoming", () => HttpResponse.json([upcomingIssue])),
    );
    render(<ReleasesPage />);

    expect(
      await screen.findByRole("button", { name: "Review releases" }),
    ).toBeTruthy();
  });

  it("skips a mine-row, toasts, and drops it from the wanted-only list", async () => {
    const store = { ...upcomingIssue };
    server.use(
      http.get("/api/upcoming", ({ request }) => {
        const url = new URL(request.url);
        const includeDownloaded =
          url.searchParams.get("include_downloaded_issues") === "true";
        if (store.Status !== "Wanted" && !includeDownloaded) {
          return HttpResponse.json([]);
        }
        return HttpResponse.json([{ ...store }]);
      }),
      http.put("/api/series/issues/:issueId/unqueue", ({ params }) => {
        expect(params.issueId).toBe(store.IssueID);
        store.Status = "Skipped";
        return HttpResponse.json({ success: true });
      }),
    );
    const user = userEvent.setup();
    render(<ReleasesPage />);

    expect(await screen.findByText("Absolute Batman")).toBeTruthy();
    await user.click(await screen.findByRole("button", { name: "Skip" }));
    expect(await screen.findByText("1 issue skipped")).toBeTruthy();
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Skip" })).toBeNull();
    });
    expect(await screen.findByText("No releases this week")).toBeTruthy();
  });

  it("toasts when Skip on My releases fails", async () => {
    server.use(
      http.get("/api/upcoming", () => HttpResponse.json([upcomingIssue])),
      http.put("/api/series/issues/:issueId/unqueue", () =>
        HttpResponse.json({ error: "boom" }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    render(<ReleasesPage />);
    await user.click(await screen.findByRole("button", { name: "Skip" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
  });

  it("toasts when Want on My releases fails", async () => {
    server.use(
      http.get("/api/upcoming", () =>
        HttpResponse.json([{ ...upcomingIssue, Status: "Skipped" }]),
      ),
      http.put("/api/series/issues/:issueId/queue", () =>
        HttpResponse.json({ error: "boom" }, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    render(<ReleasesPage />);
    await user.click(await screen.findByRole("button", { name: "Want" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
  });

  it("exposes aria-pressed on view toggles and flips it when switching", async () => {
    const user = userEvent.setup();
    render(<ReleasesPage />);

    const mine = await screen.findByRole("button", { name: "Mine" });
    const industry = screen.getByRole("button", { name: "Industry" });
    expect(mine.getAttribute("aria-pressed")).toBe("true");
    expect(industry.getAttribute("aria-pressed")).toBe("false");

    await user.click(industry);
    expect(mine.getAttribute("aria-pressed")).toBe("false");
    expect(industry.getAttribute("aria-pressed")).toBe("true");
  });
});
