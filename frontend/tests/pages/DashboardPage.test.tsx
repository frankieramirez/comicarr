/**
 * Tests for the DashboardPage component (Direction B redesign).
 *
 * Uses getByText / queryByText which throw or return null respectively.
 * No @testing-library/jest-dom needed.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useLocation } from "react-router-dom";
import { server } from "../mocks/server";
import { http, HttpResponse } from "msw";
import { createTestQueryClient, render, screen, within } from "../test-utils";
import DashboardPage from "@/pages/DashboardPage";

/** Enough of `GET /api/search/health` for the band to resolve to "healthy". */
const HEALTHY_HEALTH = {
  viable_route: true,
  routes: {
    nzb: {
      ready: true,
      reason: "ready",
      downstream: "sabnzbd",
      providers: [
        { name: "nzbgeek", kind: "newznab", blocked: false, attempted: true },
      ],
    },
  },
  workers: { search: { state: "idle", alive: true, healthy: true } },
  maintenance: { blocked: false },
  blocked_producer_count: 0,
  providers: [
    { provider: "nzbgeek", lastrun: Math.floor(Date.now() / 1000) - 720 },
  ],
};

function LocationProbe() {
  return <div data-testid="location">{useLocation().pathname}</div>;
}

function FullLocationProbe() {
  const location = useLocation();
  return (
    <div data-testid="full-location">{`${location.pathname}${location.search}`}</div>
  );
}

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("renders the dashboard heading", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Dashboard")).toBeTruthy();
    });
  });

  it("keeps library totals in the header, not a score beside health", async () => {
    render(<DashboardPage />);

    // The v2 dashboard states the library in the header subtitle. Completion
    // never appears: it reads as a health score (dashboard-spec.md §3.6).
    expect(await screen.findByText("10 series · 250 issues")).toBeTruthy();
    expect(screen.queryByText(/known issues held/)).toBeNull();
    expect(screen.queryByText("Completion")).toBeNull();
    // The Queue tile is gone: it counted active DDL items only, so it read
    // "0 queued" while SABnzbd was downloading (dashboard-spec.md §3.7).
    expect(screen.queryByText("Queue")).toBeNull();
  });

  it("renders the recent activity preview from the narrative stream", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Recent activity")).toBeTruthy();
    });

    // Sentence voice from the Activity Center lexicon, not a snatched status.
    expect(await screen.findByText(/Grabbed/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Spider-Man #1" })).toBeTruthy();
    expect(
      within(screen.getByTestId("recent-activity")).getByRole("link", {
        name: "Activity",
      }),
    ).toBeTruthy();

    // Nothing on the page claims a queue depth any more.
    expect(screen.queryByText("Active queue")).toBeNull();
    expect(screen.queryByRole("link", { name: "open queue →" })).toBeNull();
    expect(screen.queryByText(/in queue/)).toBeNull();
  });

  it("shows a failed attempt that never reached the snatched table", async () => {
    server.use(
      http.get("/api/dashboard/activity", () =>
        HttpResponse.json({
          days: 30,
          events: [
            {
              event_id: 10,
              created_at: "2026-04-05T12:05:00",
              activity: "grab",
              status: "failed",
              subject_type: "issue",
              subject_id: "901",
              subject_label: "Saga #12",
              provider: "nzb",
              parent_series_id: "42",
            },
            {
              event_id: 11,
              created_at: "2026-04-05T12:00:00",
              activity: "import",
              status: "succeeded",
              subject_type: "issue",
              subject_id: "101",
              subject_label: "Spider-Man #1",
              provider: "local",
              parent_series_id: "1",
            },
          ],
        }),
      ),
    );

    render(<DashboardPage />);

    // Failure and success share the timeline; failure uses the "Couldn't" voice.
    expect(await screen.findByText(/Couldn't grab/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Saga #12" })).toBeTruthy();
    expect(screen.getByText(/Imported/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Spider-Man #1" })).toBeTruthy();

    // Deep-link matches Activity Center subject routing.
    expect(
      (
        screen.getByRole("link", { name: "Saga #12" }) as HTMLAnchorElement
      ).getAttribute("href"),
    ).toBe("/library/42/issue/901");
  });

  it("reports in-flight work from the activity status endpoint", async () => {
    render(<DashboardPage />);

    // The default fixture reports 2 in flight, none of it stuck or recovered.
    const rail = await screen.findByRole("region", { name: "In flight" });
    expect(
      within(rail).getByText("Moving now").parentElement?.textContent,
    ).toBe("Moving now2");
    expect(
      within(rail).getByText("Stuck over 7 days").parentElement?.textContent,
    ).toBe("Stuck over 7 days0");
  });

  it("surfaces a quiet needs-attention line on the default empty band", async () => {
    render(<DashboardPage />);

    // Default mock has zero groups — calm, not an empty card with a heading.
    expect(await screen.findByText("Nothing needs you")).toBeTruthy();
    expect(
      screen.queryByRole("region", { name: "Needs attention" }),
    ).toBeNull();
  });

  it("qualifies the in-flight count with restart recoveries", async () => {
    server.use(
      http.get("/api/activity/status", () =>
        HttpResponse.json({ in_flight: 12, recovery_pending: 3, attention: 0 }),
      ),
    );

    render(<DashboardPage />);

    // Qualified, never summed: 12 total, of which 3 survived a restart.
    expect(await screen.findByText("3 recovered from a restart")).toBeTruthy();
    const rail = screen.getByRole("region", { name: "In flight" });
    expect(
      within(rail).getByText("Moving now").parentElement?.textContent,
    ).toBe("Moving now12");
  });

  it("splits in-flight work into moving and stuck over 7 days", async () => {
    server.use(
      http.get("/api/activity/status", () =>
        HttpResponse.json({
          in_flight: 296,
          in_flight_stuck: 295,
          attention: 0,
        }),
      ),
    );

    render(<DashboardPage />);

    const rail = await screen.findByRole("region", { name: "In flight" });
    expect(
      within(rail).getByText("Stuck over 7 days").parentElement?.textContent,
    ).toBe("Stuck over 7 days295");
    expect(within(rail).getByRole("img").getAttribute("aria-label")).toBe(
      "1 moving, 295 stuck",
    );
  });

  it("says nothing is in flight rather than nothing at all", async () => {
    server.use(
      http.get("/api/activity/status", () =>
        HttpResponse.json({ in_flight: 0, recovery_pending: 0, attention: 0 }),
      ),
    );

    render(<DashboardPage />);

    expect(await screen.findByText("nothing in flight")).toBeTruthy();
  });

  it("says so when the in-flight count cannot be read", async () => {
    server.use(
      http.get("/api/activity/status", () =>
        HttpResponse.json({ detail: "unavailable" }, { status: 503 }),
      ),
    );

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("In flight unavailable")).toBeTruthy();
    });
    expect(screen.queryByText("nothing in flight")).toBeNull();
  });

  it("starts scans for each configured library from the dashboard", async () => {
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(["comicScanProgress"], {
      status: "completed",
      progress: {},
    });
    queryClient.setQueryData(["mangaScanProgress"], {
      status: "completed",
      progress: {},
    });
    let comicScans = 0;
    let mangaScans = 0;
    server.use(
      http.post("/api/import/comic/scan", () => {
        comicScans += 1;
        return HttpResponse.json({ success: true, message: "started" });
      }),
      http.post("/api/import/manga/scan", () => {
        mangaScans += 1;
        return HttpResponse.json({ success: true, message: "started" });
      }),
      http.get("/api/import/comic/progress", () =>
        HttpResponse.json({ status: "scanning", progress: {} }),
      ),
      http.get("/api/import/manga/progress", () =>
        HttpResponse.json({ status: "scanning", progress: {} }),
      ),
    );

    const user = userEvent.setup();
    render(
      <>
        <DashboardPage />
        <LocationProbe />
      </>,
      { queryClient, route: "/", useMemoryRouter: true },
    );
    const scanButton = await screen.findByRole("button", {
      name: "Scan libraries",
    });
    await waitFor(() =>
      expect(scanButton.hasAttribute("disabled")).toBe(false),
    );
    await user.click(scanButton);

    await waitFor(() => {
      expect(comicScans).toBe(1);
      expect(mangaScans).toBe(1);
    });
    expect(
      screen
        .getByRole("button", { name: "Scanning…" })
        .hasAttribute("disabled"),
    ).toBe(true);
    await waitFor(() => {
      expect(screen.getByTestId("location").textContent).toBe("/import");
    });
  });

  it("reports a partial library scan startup failure", async () => {
    server.use(
      http.post("/api/import/comic/scan", () =>
        HttpResponse.json({ success: true, message: "started" }),
      ),
      http.post("/api/import/manga/scan", () =>
        HttpResponse.json({ detail: "busy" }, { status: 409 }),
      ),
      http.get("/api/import/comic/progress", () =>
        HttpResponse.json({ status: "completed", progress: {} }),
      ),
    );

    const user = userEvent.setup();
    render(<DashboardPage />);
    await user.click(
      await screen.findByRole("button", { name: "Scan libraries" }),
    );

    await waitFor(() => {
      expect(
        screen.getByText(
          "One library scan started, but another failed to start.",
        ),
      ).toBeTruthy();
    });
  });

  it("renders this-week upcoming list", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("This week")).toBeTruthy();
    });

    await waitFor(() => {
      expect(screen.getByText("Batman")).toBeTruthy();
    });
  });

  it("shows empty states when no data", async () => {
    server.use(
      http.get("/api/dashboard/activity", () =>
        HttpResponse.json({ days: 30, events: [] }),
      ),
      http.get("/api/dashboard/upcoming", () =>
        HttpResponse.json({ releases: [] }),
      ),
      http.get("/api/dashboard/scan-targets", () =>
        HttpResponse.json({ comic: false, manga: false }),
      ),
    );

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText(/No activity in the last 30 days/)).toBeTruthy();
      expect(screen.getByText("nothing upcoming this week")).toBeTruthy();
    });
    expect(
      screen
        .getByRole("button", { name: "Scan libraries" })
        .hasAttribute("disabled"),
    ).toBe(true);
  });

  it("links the recent empty state to the Activity Center", async () => {
    server.use(
      http.get("/api/dashboard/activity", () =>
        HttpResponse.json({ days: 30, events: [] }),
      ),
    );

    render(<DashboardPage />);

    expect(
      await screen.findByRole("link", { name: "open full activity" }),
    ).toBeTruthy();
  });

  it("keeps every other panel rendered when one source fails", async () => {
    server.use(
      http.get("/api/dashboard/activity", () =>
        HttpResponse.json({ detail: "Database unavailable" }, { status: 503 }),
      ),
    );

    render(<DashboardPage />);

    // The failing panel says so; it does not claim a quiet month.
    await waitFor(() => {
      expect(screen.getByText("Recent activity unavailable")).toBeTruthy();
    });
    expect(screen.queryByText(/No activity in the last 30 days/)).toBeNull();

    // Neighbours still render their own content.
    expect(screen.getByRole("region", { name: "In flight" })).toBeTruthy();
    expect(screen.getByText("Batman")).toBeTruthy();
  });

  it("retries only the panel that failed", async () => {
    let activityRequests = 0;
    let upcomingRequests = 0;
    server.use(
      http.get("/api/dashboard/activity", () => {
        activityRequests += 1;
        return activityRequests === 1
          ? HttpResponse.json(
              { detail: "Database unavailable" },
              { status: 503 },
            )
          : HttpResponse.json({
              days: 30,
              events: [
                {
                  event_id: 1,
                  created_at: "2026-04-05T12:00:00",
                  activity: "grab",
                  status: "succeeded",
                  subject_type: "issue",
                  subject_id: "101",
                  subject_label: "Spider-Man #1",
                  provider: "nzb",
                  parent_series_id: "1",
                },
              ],
            });
      }),
      http.get("/api/dashboard/upcoming", () => {
        upcomingRequests += 1;
        return HttpResponse.json({ releases: [] });
      }),
    );

    const user = userEvent.setup();
    render(<DashboardPage />);

    // Each retry is named for its own panel, so it is unambiguous.
    await user.click(
      await screen.findByRole("button", { name: "Retry Recent activity" }),
    );

    await waitFor(() => {
      expect(screen.getByRole("link", { name: "Spider-Man #1" })).toBeTruthy();
    });
    expect(activityRequests).toBe(2);
    expect(upcomingRequests).toBe(1);
  });

  it("reports an unavailable KPI instead of a zero it cannot back", async () => {
    server.use(
      http.get("/api/dashboard/library", () =>
        HttpResponse.json({ detail: "Database unavailable" }, { status: 503 }),
      ),
    );

    render(<DashboardPage />);

    // The header says so rather than claiming "0 series" — while the
    // in-flight line, on its own endpoint, still answers.
    await waitFor(() => {
      expect(screen.getByText("library unavailable")).toBeTruthy();
    });
    expect(screen.queryByText(/0 series/)).toBeNull();
    expect(screen.getByRole("region", { name: "In flight" })).toBeTruthy();
  });

  it("says so when the scan targets cannot be read", async () => {
    server.use(
      http.get("/api/dashboard/scan-targets", () =>
        HttpResponse.json({ detail: "Config unavailable" }, { status: 503 }),
      ),
    );

    render(<DashboardPage />);

    // A failed read must not read as "no library configured".
    await waitFor(() => {
      expect(screen.getByText("Scan targets unavailable")).toBeTruthy();
    });
    expect(screen.queryByRole("button", { name: "Scan libraries" })).toBeNull();
    expect(
      screen.getByRole("button", { name: "Retry Scan targets" }),
    ).toBeTruthy();
  });

  it("keeps no chat surface above the fold", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("This week")).toBeTruthy();
    });
    // Ask is demoted to the bottom of the page, and the recent-chats card that
    // sat beside "This week" goes with it (dashboard-spec.md §3.8).
    expect(screen.queryByText("Recent chats")).toBeNull();
    expect(screen.queryByRole("link", { name: "all →" })).toBeNull();
  });

  it("orders the page by the priority of questions", async () => {
    server.use(
      http.get("/api/search/health", () => HttpResponse.json(HEALTHY_HEALTH)),
      http.get("/api/ai/status", () =>
        HttpResponse.json({ configured: true, circuit_state: "closed" }),
      ),
    );

    const { container } = render(<DashboardPage />);

    // Wait for every section to have resolved so none is still a skeleton.
    const health = await screen.findByRole("region", {
      name: "Acquisition health",
    });
    await screen.findByText("Nothing needs you");
    await screen.findByTestId("ask-bar");

    // Source order is the one-column reading order: what needs me, whether
    // it is working, what is happening, then the library, and only then the
    // feature entry point. On wide screens the middle three sit in the rail.
    const byId = (id: string) => {
      const node = container.querySelector(`[data-testid="${id}"]`);
      expect(node, `missing ${id}`).toBeTruthy();
      return node as HTMLElement;
    };
    const anchors = [
      byId("needs-attention-empty"),
      health,
      byId("recent-activity"),
      byId("recently-added"),
      byId("most-wanted"),
      byId("ask-bar"),
    ];

    for (let i = 1; i < anchors.length; i += 1) {
      // DOCUMENT_POSITION_FOLLOWING === 4: each anchor precedes the next one.
      expect(
        anchors[i - 1].compareDocumentPosition(anchors[i]) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
  });

  it("hides the ask bar unless an AI provider is configured", async () => {
    render(<DashboardPage />);

    await screen.findByText("This week");
    expect(screen.queryByTestId("ask-bar")).toBeNull();
  });

  it("puts the rail beside the main column on wide screens only", async () => {
    const { container } = render(<DashboardPage />);

    await screen.findByText("This week");
    await screen.findByText("Nothing needs you");

    const grid = container.querySelector('[data-testid="middle-columns"]');
    expect(grid).toBeTruthy();
    expect(grid!.className).toContain("grid-cols-1");
    expect(grid!.className).toContain("lg:grid-cols-[minmax(0,1fr)_352px]");

    const rail = grid!.querySelector("aside");
    expect(rail).toBeTruthy();
    expect(rail!.contains(screen.getByTestId("recent-activity"))).toBe(true);
    expect(rail!.contains(screen.getByTestId("this-week"))).toBe(true);
    expect(rail!.contains(screen.getByTestId("needs-attention-empty"))).toBe(
      false,
    );
  });

  it("puts needs-attention and in flight on one row without coupling them", async () => {
    server.use(
      http.get("/api/attention", () =>
        HttpResponse.json({ detail: "unavailable" }, { status: 503 }),
      ),
    );

    render(<DashboardPage />);

    // Sharing a row is a layout fact, not a data one: a failed band still
    // leaves the in-flight count, on its own endpoint, answering.
    await waitFor(() => {
      expect(screen.getByText("Needs attention unavailable")).toBeTruthy();
    });
    expect(screen.getByRole("region", { name: "In flight" })).toBeTruthy();
    expect(screen.getByTestId("attention-inflight-row")).toBeTruthy();
  });

  it("hands a typed question to the chat workspace", async () => {
    server.use(
      http.get("/api/ai/status", () =>
        HttpResponse.json({ configured: true, circuit_state: "closed" }),
      ),
    );
    const user = userEvent.setup();
    render(
      <>
        <DashboardPage />
        <FullLocationProbe />
      </>,
      { route: "/", useMemoryRouter: true },
    );

    const ask = await screen.findByRole("textbox", {
      name: "Ask about your library",
    });
    await user.type(ask, "Which runs have gaps?");

    await user.click(screen.getByRole("button", { name: "Ask Comicarr" }));
    await waitFor(() => {
      expect(screen.getByTestId("full-location").textContent).toBe(
        "/chat?q=Which%20runs%20have%20gaps%3F",
      );
    });
  });
});
