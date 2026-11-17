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
      /md:grid-cols-\[minmax\(0,1fr\)_110px_160px_110px_120px\]/,
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

  it("filters and sorts the week, and counts each format", async () => {
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
    // Publisher is the default sort, grouped under each publisher.
    expect(titles()[0]).toContain("Batman");
    expect(
      screen.getAllByTestId("weekly-publisher-group").map((g) => g.textContent),
    ).toEqual(["Aftershock1", "Dynamite1", "Marvel1"]);

    await user.click(screen.getByRole("combobox", { name: "Sort" }));
    await user.click(await screen.findByRole("option", { name: "Title" }));
    expect(titles()[0]).toContain("Amazing Spider-Man");
    expect(screen.queryByTestId("weekly-publisher-group")).toBeNull();

    await user.type(screen.getByLabelText("Filter releases"), "marvel");
    expect(titles()).toHaveLength(1);
    expect(titles()[0]).toContain("Amazing Spider-Man");

    const formats = screen.getByTestId("release-formats");
    expect(formats.textContent).toContain("All3");
    expect(formats.textContent).toContain("Comics3");
    expect(formats.textContent).toContain("Manga0");
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
      await screen.findByText(/No pull-list source has this week's comics/),
    ).toBeTruthy();
  });

  it("says why each pull-list source left the week empty", async () => {
    server.use(
      http.get("/api/weekly", () =>
        HttpResponse.json(
          weeklyWeek([], {
            source: "unavailable",
            pull_attempts: [
              { source: "walksoftly", reason: "failed" },
              { source: "metron", reason: "not_configured" },
              { source: "comicvine", reason: "no_releases" },
            ],
          }),
        ),
      ),
    );
    renderIndustry();

    const reason = await screen.findByText(/built-in release calendar could not be reached/);
    expect(reason.textContent).toContain("Add your Metron login in Settings");
    expect(reason.textContent).toContain(
      "ComicVine lists no comics for this week yet.",
    );
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

  it("hides review for a release whose issue is not in the library yet", async () => {
    server.use(
      http.get("/api/upcoming", () =>
        HttpResponse.json([{ ...upcomingIssue, IssueID: null }]),
      ),
    );
    render(<ReleasesPage />);

    await screen.findByText("Absolute Batman");
    expect(screen.queryByRole("button", { name: "Review releases" })).toBe(
      null,
    );
  });

  it("skips a mine-row, toasts, and drops it from the week", async () => {
    const store = { ...upcomingIssue };
    server.use(
      // Like the backend, Skipped issues leave the week's list.
      http.get("/api/upcoming", () =>
        HttpResponse.json(store.Status === "Skipped" ? [] : [{ ...store }]),
      ),
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

  it("shows only the library by default and flips to everything", async () => {
    const user = userEvent.setup();
    render(<ReleasesPage />);

    const toggle = await screen.findByTestId("library-only-toggle");
    expect(toggle.getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByTestId("popular-only-toggle")).toBeNull();

    await user.click(toggle);
    expect(
      (await screen.findByTestId("library-only-toggle")).getAttribute(
        "aria-pressed",
      ),
    ).toBe("false");
    expect(await screen.findByTestId("popular-only-toggle")).toBeTruthy();
  });

  it("remembers the library toggle between visits", async () => {
    const user = userEvent.setup();
    const first = render(<ReleasesPage />, { useMemoryRouter: true });
    await user.click(await screen.findByTestId("library-only-toggle"));
    first.unmount();

    render(<ReleasesPage />, { useMemoryRouter: true, route: "/releases" });

    expect(
      (await screen.findByTestId("library-only-toggle")).getAttribute(
        "aria-pressed",
      ),
    ).toBe("false");
  });

  const mangaRow = (overrides: Record<string, unknown> = {}) => ({
    key: "mu-10",
    source: "mangaupdates",
    mu_series_id: "10",
    COMIC: "Popular Manhwa",
    ISSUE: "412",
    chapters: "411–412",
    volume: "",
    SHIPDATE: "2026-10-13",
    PUBLISHER: null,
    format: "Manhwa",
    popular_rank: 3,
    cover: null,
    url: "https://www.mangaupdates.com/series/abc",
    ComicID: null,
    in_library: false,
    library_issue_id: null,
    issue_status: null,
    state: "not_in_library",
    ...overrides,
  });

  const withManga = (rows: unknown[], status = "ok") =>
    weeklyWeek([weeklyRow({ COMIC: "Saga", PUBLISHER: "Image" })], {
      manga: { status, rows, popular_rank: 500 },
    });

  it("lists manga by type, popular first, behind the format chips", async () => {
    server.use(
      http.get("/api/weekly", () =>
        HttpResponse.json(
          withManga([
            mangaRow(),
            mangaRow({
              key: "mu-20",
              COMIC: "Quiet Manga",
              format: "Manga",
              ISSUE: "75",
              chapters: "75",
              popular_rank: null,
            }),
            mangaRow({
              key: "mu-30",
              COMIC: "Big Manga",
              format: "Manga",
              ISSUE: "252",
              chapters: "252",
              popular_rank: 15,
            }),
          ]),
        ),
      ),
    );
    const user = userEvent.setup();
    renderIndustry();

    await screen.findByText("Saga");
    // Popular only is on: the unranked series stays out of every count.
    const formats = screen.getByTestId("release-formats");
    expect(formats.textContent).toContain("All3");
    expect(formats.textContent).toContain("Manga1");
    expect(formats.textContent).toContain("Manhwa1");
    expect(screen.queryByText("Quiet Manga")).toBeNull();
    expect(screen.getAllByText("Ch. 411–412").length).toBeGreaterThan(0);
    expect(
      screen.getAllByTestId("weekly-publisher-group").map((g) => g.textContent),
    ).toEqual(["Image1", "Manga1", "Manhwa1"]);

    await user.click(screen.getByTestId("popular-only-toggle"));
    expect(await screen.findByText("Quiet Manga")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /^Manga/ }));
    expect(screen.queryByText("Saga")).toBeNull();
    expect(screen.queryByText("Popular Manhwa")).toBeNull();
    const titles = screen
      .getAllByTestId("weekly-release-row")
      .map((row) => row.querySelector("[data-grid-title]")?.textContent);
    expect(titles).toEqual(["Big Manga Ch. 252", "Quiet Manga Ch. 75"]);
    expect(screen.getByText(/release data from/)).toBeTruthy();
  });

  it("shows library manga chapters from MangaUpdates under Only my library", async () => {
    server.use(
      http.get("/api/weekly", () =>
        HttpResponse.json(
          withManga([
            mangaRow({
              key: "mu-40",
              COMIC: "Dandadan",
              format: "Manga",
              ISSUE: "252",
              chapters: "252",
              ComicID: "md-dandadan",
              in_library: true,
              library_issue_id: "md-dandadan-252",
              issue_status: "Wanted",
              state: "wanted",
            }),
            // In the library but this chapter is not, or the series is not.
            mangaRow({
              key: "mu-41",
              COMIC: "Followed Manhwa",
              ComicID: "md-followed",
              in_library: true,
              state: "in_library",
            }),
            mangaRow(),
          ]),
        ),
      ),
    );
    render(<ReleasesPage />, {
      useMemoryRouter: true,
      route: "/releases?view=mine",
    });

    expect(await screen.findByText("Dandadan")).toBeTruthy();
    expect(screen.queryByText("Followed Manhwa")).toBeNull();
    expect(screen.queryByText("Popular Manhwa")).toBeNull();
    expect(screen.getByTestId("release-formats").textContent).toContain(
      "Manga1",
    );
  });

  it("explains an empty library week when the pull list is unavailable", async () => {
    server.use(
      http.get("/api/weekly", () =>
        HttpResponse.json(weeklyWeek([], { source: "unavailable" })),
      ),
    );
    render(<ReleasesPage />, {
      useMemoryRouter: true,
      route: "/releases?view=mine",
    });

    expect(
      await screen.findByText("This week's pull list isn't available yet"),
    ).toBeTruthy();
  });

  it("notes missing comics when store dates stand in for the pull list", async () => {
    server.use(
      http.get("/api/weekly", () =>
        HttpResponse.json(weeklyWeek([], { source: "unavailable" })),
      ),
      http.get("/api/upcoming", () => HttpResponse.json([upcomingIssue])),
    );
    render(<ReleasesPage />, {
      useMemoryRouter: true,
      route: "/releases?view=mine",
    });

    await screen.findByText("Absolute Batman");
    expect(screen.getByTestId("pull-unavailable-note")).toBeTruthy();
  });

  it("filters manga to one day from the day strip", async () => {
    server.use(
      http.get("/api/weekly", () =>
        HttpResponse.json(
          withManga([
            mangaRow({ format: "Manga" }),
            mangaRow({
              key: "mu-30",
              COMIC: "Big Manga",
              format: "Manga",
              SHIPDATE: "2026-10-15",
              popular_rank: 15,
            }),
          ]),
        ),
      ),
    );
    const user = userEvent.setup();
    renderIndustry();
    await screen.findByText("Saga");
    expect(screen.queryByTestId("industry-day-strip")).toBeNull();

    await user.click(screen.getByRole("button", { name: /^Manga/ }));
    const strip = await screen.findByTestId("industry-day-strip");
    const thursday = Array.from(strip.querySelectorAll("button")).find((b) =>
      b.textContent?.startsWith("Thu"),
    );
    await user.click(thursday!);

    expect(screen.getAllByTestId("weekly-release-row")).toHaveLength(1);
    expect(screen.getByText("Big Manga")).toBeTruthy();
    expect(screen.getByTestId("day-filter-note").textContent).toContain(
      "Thursday, Oct 15",
    );

    await user.click(
      screen.getByRole("button", { name: "Show the whole week" }),
    );
    expect(screen.getAllByTestId("weekly-release-row")).toHaveLength(2);
    expect(screen.queryByTestId("day-filter-note")).toBeNull();
  });

  it("keeps library releases the pull list does not list", async () => {
    server.use(
      http.get("/api/weekly", () =>
        HttpResponse.json(weeklyWeek([], { source: "unavailable" })),
      ),
      http.get("/api/upcoming", () =>
        HttpResponse.json([{ ...upcomingIssue, Publisher: "DC" }]),
      ),
    );
    renderIndustry();

    expect(await screen.findByText("Absolute Batman")).toBeTruthy();
    expect(screen.getAllByText("#19").length).toBeGreaterThan(0);
  });

  it("explains manga releases need a manga provider", async () => {
    server.use(
      http.get("/api/weekly", () =>
        HttpResponse.json(withManga([], "disabled")),
      ),
    );
    const user = userEvent.setup();
    renderIndustry();
    await screen.findByText("Saga");

    await user.click(screen.getByRole("button", { name: /^Manhwa/ }));

    expect(
      await screen.findByText(/Turn on MangaDex or MyAnimeList/),
    ).toBeTruthy();
  });

  it("adds a manga release through its MangaDex match", async () => {
    let added: unknown = null;
    server.use(
      http.get("/api/weekly", () => HttpResponse.json(withManga([mangaRow()]))),
      http.post("/api/search/manga", () =>
        HttpResponse.json({
          results: [
            {
              id: "md-abc",
              name: "Popular Manhwa",
              comicyear: "2024",
              metadata_source: "mangadex",
              haveit: "No",
            },
          ],
          pagination: { total: 1, limit: 20, offset: 0, returned: 1 },
        }),
      ),
      http.post("/api/search/add-manga", async ({ request }) => {
        added = await request.json();
        return HttpResponse.json({ success: true, comicid: "md-abc" });
      }),
    );
    const user = userEvent.setup();
    renderIndustry();

    await user.click(
      await screen.findByRole("button", { name: "Add Popular Manhwa" }),
    );
    expect(await screen.findByRole("radio", { checked: true })).toBeTruthy();
    expect(screen.getByText(/MangaDex · 2024/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Add series" }));

    await waitFor(() => expect(added).toEqual({ id: "md-abc" }));
  });
});
