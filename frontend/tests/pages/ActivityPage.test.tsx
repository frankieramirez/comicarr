import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { render, screen, waitFor, within } from "../test-utils";
import ActivityPage from "@/pages/ActivityPage";

const queueItem = {
  ID: "queue-1",
  series: "Absolute Flash",
  year: "2026",
  filename: "Absolute Flash 013.cbz",
  size: "10 MB",
  issueid: "issue-13",
  comicid: "comic-1",
  link: "",
  status: "Downloading",
  remote_filesize: "10 MB",
  updated_date: "2026-07-10 08:40",
  site: "DDL(GetComics)",
  submit_date: "2026-07-10 08:35",
};

function emptyTimelineHandlers() {
  return [
    http.get("/api/activity/timeline", () =>
      HttpResponse.json({
        results: [],
        total: 0,
        limit: 100,
        offset: 0,
        has_more: false,
      }),
    ),
    http.get("/api/attention", () =>
      HttpResponse.json({
        results: [],
        total: 0,
        member_total: 0,
        preview_cap: 5,
      }),
    ),
  ];
}

function bandGroup(overrides = {}) {
  return {
    group_key: "42|download_failed",
    comicid: "42",
    series_label: "Saga",
    base_reason: "download_failed",
    reason_phrase: "the download failed",
    member_count: 1,
    newest_updated_at: "2026-07-10 12:00:00",
    oldest_updated_at: "2026-07-10 12:00:00",
    stage: "failed",
    available_actions: ["retry", "stop_wanting"],
    members: [
      {
        release_key: "rk-failed-1",
        issue_label: "Saga #9",
        issueid: "iss-9",
        stage: "failed",
        updated_date: "2026-07-10 12:00:00",
      },
    ],
    ...overrides,
  };
}

describe("ActivityPage", () => {
  it("defaults to the Timeline tab and renames Queue / History", async () => {
    server.use(...emptyTimelineHandlers());
    render(<ActivityPage />, { route: "/activity", useMemoryRouter: true });

    expect(await screen.findByText("Nothing has happened yet")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Timeline" })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Direct Downloads" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Download History" }),
    ).toBeTruthy();
    // Queue-specific chrome must not be the default landing surface.
    expect(
      screen.queryByRole("textbox", { name: "Filter queue activity" }),
    ).toBeNull();
  });

  it("renders Variant A timeline rows, a bounded band preview, and scoped query params", async () => {
    let timelineUrl: URL | undefined;
    let bandUrl: URL | undefined;

    server.use(
      http.get("/api/activity/timeline", ({ request }) => {
        timelineUrl = new URL(request.url);
        return HttpResponse.json({
          results: [
            {
              event_id: 1,
              created_at: "2026-07-10 10:00:00",
              activity: "grab",
              status: "succeeded",
              subject_type: "issue",
              subject_id: "iss-1",
              subject_label: "Saga #1",
              parent_series_id: "ser-1",
              provider: "DDL",
            },
            {
              event_id: 2,
              created_at: "2026-07-10 10:05:00",
              activity: "import",
              status: "succeeded",
              subject_type: "issue",
              subject_id: "iss-1",
              subject_label: "Saga #1",
              parent_series_id: "ser-1",
            },
            {
              event_id: 3,
              created_at: "2026-07-10 11:00:00",
              activity: "add",
              status: "succeeded",
              subject_type: "series",
              subject_id: "ser-2",
              subject_label: "Invincible",
            },
          ],
          total: 3,
          limit: 100,
          offset: 0,
          has_more: false,
        });
      }),
      http.get("/api/attention", ({ request }) => {
        bandUrl = new URL(request.url);
        // Eight groups against a preview cap of five: the fold has to appear.
        return HttpResponse.json({
          results: Array.from({ length: 8 }, (_, i) =>
            bandGroup({
              group_key: `4${i}|download_failed`,
              comicid: `4${i}`,
              series_label: `Series ${i}`,
              member_count: i + 1,
              newest_updated_at: `2026-07-1${i} 12:00:00`,
            }),
          ),
          total: 8,
          member_total: 36,
          preview_cap: 5,
        });
      }),
    );

    render(<ActivityPage />, {
      route: "/activity?scope_type=series&scope_id=ser-1",
      useMemoryRouter: true,
    });

    // Multi-event story collapses to the closer sentence (inline entity link).
    expect(
      await screen.findByText((_content, node) => {
        const text = node?.textContent ?? "";
        return (
          node?.tagName === "SPAN" &&
          text.includes("Imported") &&
          text.includes("Saga #1")
        );
      }),
    ).toBeTruthy();
    // Group-of-one plain row for the series add.
    expect(screen.getByRole("link", { name: "Invincible" })).toBeTruthy();
    expect(screen.getByText(/Added/)).toBeTruthy();
    // Always-collapsed multi-event story: no phase trail expansion chrome.
    expect(screen.queryByRole("button", { name: /^2$/ })).toBeNull();

    expect(timelineUrl?.searchParams.get("scope_type")).toBe("series");
    expect(timelineUrl?.searchParams.get("scope_id")).toBe("ser-1");
    expect(bandUrl?.searchParams.get("scope_type")).toBe("series");
    expect(bandUrl?.searchParams.get("scope_id")).toBe("ser-1");

    // The band is bounded: five cards plus a fold, never one row per problem.
    // Ranking is the server's — the client shows the first `preview_cap` it is
    // given and never re-sorts, so the band and the triage route agree.
    const band = screen.getByLabelText("Needs attention");
    expect(band).toBeTruthy();
    expect(screen.getByText("8 need attention")).toBeTruthy();
    expect(screen.getByText("36 issues · clears only by action")).toBeTruthy();
    expect(screen.getByText("Series 4")).toBeTruthy();
    expect(screen.queryByText("Series 5")).toBeNull();
    expect(screen.getByText("+3")).toBeTruthy();

    // The band routes; it never resolves. No action buttons live on it.
    expect(within(band).queryByRole("button")).toBeNull();
    expect(
      screen.getByRole("link", { name: "See all 8 →" }).getAttribute("href"),
    ).toBe("/activity/attention?scope_type=series&scope_id=ser-1");
  });

  it("labels terminal and manual-review queue rows truthfully and only retries failed DDL work after confirmation", async () => {
    const queueRows = [
      {
        ...queueItem,
        ID: "failed-ddl",
        series: "Failed Series",
        status: "Failed",
      },
      {
        ...queueItem,
        ID: "unknown-ddl",
        series: "Unknown Series",
        status: "Unknown",
      },
      {
        ...queueItem,
        ID: "manual-ddl",
        series: "Manual Series",
        status: "manual_review",
      },
      {
        ...queueItem,
        ID: "active-ddl",
        series: "Active Series",
        status: "Downloading",
      },
    ];
    const confirm = vi.fn(() => true);
    let requeueCalls = 0;
    vi.stubGlobal("confirm", confirm);
    server.use(
      http.get("/api/downloads/queue", () =>
        HttpResponse.json({
          queue: queueRows,
          pagination: { total: 4, limit: 25, offset: 0, has_more: false },
        }),
      ),
      http.post("/api/downloads/failed-ddl/requeue", () => {
        requeueCalls += 1;
        return HttpResponse.json({ success: true });
      }),
    );
    const user = userEvent.setup();
    render(<ActivityPage />, {
      route: "/activity?view=queue",
      useMemoryRouter: true,
    });

    await screen.findByText("Failed Series");
    expect(screen.getByLabelText(/failed: terminal/i)).toBeTruthy();
    expect(
      screen.getByLabelText(/unknown: manual review required/i),
    ).toBeTruthy();
    expect(
      screen.getByLabelText(/manual review: requires attention/i),
    ).toBeTruthy();
    expect(screen.getByLabelText(/downloading: active/i)).toBeTruthy();

    expect(
      screen.queryByRole("button", { name: /requeue unknown series/i }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: /requeue manual series/i }),
    ).toBeNull();

    await user.click(
      screen.getByRole("button", { name: /requeue failed series/i }),
    );

    expect(confirm).toHaveBeenCalledOnce();
    await waitFor(() => {
      expect(requeueCalls).toBe(1);
    });
    expect(await screen.findByText("Direct download requeued.")).toBeTruthy();
  });

  /**
   * The server-paginated model gets no page reset from TanStack:
   * `autoResetPageIndex` is inert under `manualPagination` (#360), so this
   * invariant has no owner but the caller. It was hand-rolled inside
   * `useActivityTableState`, which #393 deleted, and nothing else pinned it —
   * a reset that quietly stopped happening would leave a user on page 3 of a
   * result set that no longer has one.
   */
  it("returns to the first page when the sort or the filter changes", async () => {
    const requests: URL[] = [];
    server.use(
      http.get("/api/downloads/queue", ({ request }) => {
        const url = new URL(request.url);
        requests.push(url);
        const offset = Number(url.searchParams.get("offset") || 0);
        return HttpResponse.json({
          queue: [{ ...queueItem, ID: `queue-${offset}` }],
          pagination: { total: 90, limit: 25, offset, has_more: true },
        });
      }),
    );

    const user = userEvent.setup();
    render(<ActivityPage />, {
      route: "/activity?view=queue",
      useMemoryRouter: true,
    });
    await screen.findByText("Absolute Flash");

    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => {
      expect(requests.at(-1)?.searchParams.get("offset")).toBe("25");
    });

    await user.click(screen.getByRole("button", { name: /Updated/ }));
    await waitFor(() => {
      const last = requests.at(-1);
      expect(last?.searchParams.get("order")).toBe("asc");
      expect(last?.searchParams.get("offset")).toBe("0");
    });

    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => {
      expect(requests.at(-1)?.searchParams.get("offset")).toBe("25");
    });

    await user.type(
      screen.getByRole("textbox", { name: "Filter queue activity" }),
      "flash",
    );
    await waitFor(() => {
      const last = requests.at(-1);
      expect(last?.searchParams.get("q")).toBe("flash");
      expect(last?.searchParams.get("offset")).toBe("0");
    });
  });

  it("filters, sorts, and paginates the live queue through the API", async () => {
    const requests: URL[] = [];
    server.use(
      http.get("/api/downloads/queue", ({ request }) => {
        const url = new URL(request.url);
        requests.push(url);
        const offset = Number(url.searchParams.get("offset") || 0);
        return HttpResponse.json({
          queue: offset === 0 ? [queueItem] : [],
          pagination: {
            total: offset === 0 ? 30 : 20,
            limit: 25,
            offset,
            has_more: offset === 0,
          },
        });
      }),
    );

    const user = userEvent.setup();
    render(<ActivityPage />, {
      route: "/activity?view=queue",
      useMemoryRouter: true,
    });

    await screen.findByText("Absolute Flash");
    await user.type(
      screen.getByRole("textbox", { name: "Filter queue activity" }),
      "flash",
    );
    await waitFor(() => {
      expect(
        requests.some((url) => url.searchParams.get("q") === "flash"),
      ).toBe(true);
    });

    await user.click(screen.getByRole("button", { name: /Updated/ }));
    await waitFor(() => {
      expect(
        requests.some(
          (url) =>
            url.searchParams.get("sort") === "updated" &&
            url.searchParams.get("order") === "asc",
        ),
      ).toBe(true);
    });

    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => {
      expect(
        requests.some((url) => url.searchParams.get("offset") === "25"),
      ).toBe(true);
    });
    expect(await screen.findByText("No matching queue items")).toBeTruthy();
    expect(screen.queryByText(/\d+–\d+ of \d+/)).toBeNull();
    expect(
      screen.getByRole("button", { name: "Previous" }).hasAttribute("disabled"),
    ).toBe(false);
    await user.click(screen.getByRole("button", { name: "Previous" }));
    await waitFor(() => {
      expect(requests.at(-1)?.searchParams.get("offset")).toBe("0");
    });
  });

  it("renders the in-flight items from the dedicated endpoint when state=in_flight", async () => {
    let inFlightCalls = 0;
    let timelineCalls = 0;
    server.use(
      http.get("/api/activity/in-flight", () => {
        inFlightCalls += 1;
        return HttpResponse.json({
          results: [
            {
              kind: "run",
              item_id: 11,
              run_id: "run-1",
              state: "running",
              label: "Saga #1",
              entity_type: "issue",
              entity_id: "iss-1",
              comicid: "42",
              issueid: "iss-1",
              command_kind: "search_issue",
              updated_at: "2026-07-10 10:01:00",
            },
            {
              kind: "journal",
              release_key: "open-pp",
              stage: "post_processing",
              label: "Invincible #12",
              issueid: "iss-10",
              comicid: "7",
              provider: "DDL",
              updated_at: "2026-07-10 12:00:00",
            },
          ],
          total: 2,
        });
      }),
      http.get("/api/activity/timeline", () => {
        timelineCalls += 1;
        return HttpResponse.json({
          results: [],
          total: 0,
          limit: 100,
          offset: 0,
          has_more: false,
        });
      }),
      http.get("/api/downloads/queue", () =>
        HttpResponse.json({
          queue: [queueItem],
          pagination: { total: 1, limit: 25, offset: 0, has_more: false },
        }),
      ),
    );

    render(<ActivityPage />, {
      route: "/activity?state=in_flight",
      useMemoryRouter: true,
    });

    expect(await screen.findByText("Saga #1")).toBeTruthy();
    expect(screen.getByText("Invincible #12")).toBeTruthy();
    expect(screen.getByText(/searching/i)).toBeTruthy();
    expect(screen.getByText(/post-processing/i)).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "In flight" }).getAttribute(
        "aria-pressed",
      ),
    ).toBe("true");

    // Same set as the status-bar count — not the timeline and not the DDL queue.
    expect(screen.queryByText("Nothing has happened yet")).toBeNull();
    expect(screen.queryByText("Absolute Flash")).toBeNull();
    expect(
      screen.queryByRole("textbox", { name: "Filter queue activity" }),
    ).toBeNull();
    expect(inFlightCalls).toBeGreaterThan(0);
    expect(timelineCalls).toBe(0);
  });

  it("uses the shared table for history with newest-first defaults", async () => {
    let historyRequest: URL | undefined;
    server.use(
      http.get("/api/downloads/history", ({ request }) => {
        historyRequest = new URL(request.url);
        return HttpResponse.json({
          history: [
            {
              IssueID: "issue-13",
              ComicName: "Absolute Flash",
              Issue_Number: "13",
              Size: 0,
              DateAdded: "2026-07-10 08:40:00",
              Status: "Post-Processed",
              FolderName: "",
              ComicID: "comic-1",
              Provider: "NZBGeek",
            },
          ],
          pagination: { total: 1, limit: 25, offset: 0, has_more: false },
        });
      }),
    );

    const user = userEvent.setup();
    render(<ActivityPage />, {
      route: "/activity?view=history",
      useMemoryRouter: true,
    });

    await screen.findByText("Absolute Flash");
    expect(historyRequest?.searchParams.get("sort")).toBe("date");
    expect(historyRequest?.searchParams.get("order")).toBe("desc");
    expect(screen.getByRole("button", { name: /Date/ })).toBeTruthy();
    await user.type(
      screen.getByRole("textbox", { name: "Filter download history" }),
      "nzb",
    );
    await waitFor(() => {
      expect(historyRequest?.searchParams.get("q")).toBe("nzb");
    });
  });
});
