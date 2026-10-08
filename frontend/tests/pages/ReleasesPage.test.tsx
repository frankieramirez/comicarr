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

  it("uses a phone weekly grid that keeps title and status", async () => {
    server.use(
      http.get("/api/weekly", () =>
        HttpResponse.json([
          {
            COMIC: "Absolute Batman",
            ISSUE: "19",
            PUBLISHER: "DC",
            SHIPDATE: "2026-08-12",
            STATUS: "Wanted",
            ComicID: "comic-1",
          },
        ]),
      ),
    );
    render(<ReleasesPage />, {
      useMemoryRouter: true,
      route: "/releases?view=all",
    });

    const row = await screen.findByTestId("weekly-release-row");
    expect(row.className).toMatch(/grid-cols-\[minmax\(0,1fr\)_auto\]/);
    expect(row.className).toMatch(
      /md:grid-cols-\[minmax\(0,1fr\)_80px_160px_100px\]/,
    );
    expect(row.querySelectorAll(".max-md\\:hidden").length).toBeGreaterThan(0);
    const phoneId = screen.getByTestId("phone-row-id");
    expect(phoneId.textContent).toContain("#19");
    expect(phoneId.className).toMatch(/hidden/);
    expect(phoneId.className).toMatch(/max-md:inline/);
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
