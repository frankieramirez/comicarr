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
import { createTestQueryClient, render, screen } from "../test-utils";
import DashboardPage from "@/pages/DashboardPage";

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

  it("renders KPI strip with stats", async () => {
    render(<DashboardPage />);

    // KPI labels appear immediately; values arrive once the query resolves.
    await waitFor(() => {
      expect(screen.getByText("50.0%")).toBeTruthy();
    });

    expect(screen.getByText("Active series")).toBeTruthy();
    expect(screen.getByText("Issues")).toBeTruthy();
    expect(screen.getByText("Completion")).toBeTruthy();
    // The Queue tile is gone: it counted active DDL items only, so it read
    // "0 queued" while SABnzbd was downloading (dashboard-spec.md §3.7).
    expect(screen.queryByText("Queue")).toBeNull();
    expect(screen.getByText("10")).toBeTruthy();
    expect(screen.getByText("250")).toBeTruthy();
  });

  it("renders the recent activity preview without a queue panel", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Recent activity")).toBeTruthy();
    });

    await waitFor(() => {
      expect(screen.getByText("Spider-Man #1")).toBeTruthy();
    });
    expect(screen.getAllByText(/ago$/).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "open history →" })).toBeTruthy();

    // Nothing on the page claims a queue depth any more.
    expect(screen.queryByText("Active queue")).toBeNull();
    expect(screen.queryByRole("link", { name: "open queue →" })).toBeNull();
    expect(screen.queryByText(/in queue/)).toBeNull();
  });

  it("reports in-flight work from the activity status endpoint", async () => {
    render(<DashboardPage />);

    // The default fixture reports 2 in flight, none of it recovered.
    expect(
      await screen.findByRole("link", { name: "In flight" }),
    ).toBeTruthy();
    expect(screen.getByText("2 in flight")).toBeTruthy();
  });

  it("surfaces a quiet needs-attention line on the default empty band", async () => {
    render(<DashboardPage />);

    // Default mock has zero groups — calm, not an empty card with a heading.
    expect(await screen.findByText("Nothing needs you")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Needs attention" })).toBeNull();
  });

  it("qualifies the in-flight count with restart recoveries", async () => {
    server.use(
      http.get("/api/activity/status", () =>
        HttpResponse.json({ in_flight: 12, recovery_pending: 3, attention: 0 }),
      ),
    );

    render(<DashboardPage />);

    // Qualified, never summed: 12 total, of which 3 survived a restart.
    expect(
      await screen.findByText("12 in flight (3 recovered from a restart)"),
    ).toBeTruthy();
    expect(screen.queryByText("15 in flight")).toBeNull();
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
      expect(screen.getByText(/no activity in the last 30 days/)).toBeTruthy();
      expect(screen.getByText("nothing upcoming this week")).toBeTruthy();
    });
    expect(
      screen
        .getByRole("button", { name: "Scan libraries" })
        .hasAttribute("disabled"),
    ).toBe(true);
  });

  it("links the recent empty state to the full history", async () => {
    server.use(
      http.get("/api/dashboard/activity", () =>
        HttpResponse.json({ days: 30, events: [] }),
      ),
    );

    render(<DashboardPage />);

    expect(
      await screen.findByRole("link", { name: "open full history" }),
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
    expect(screen.queryByText(/no activity in the last 30 days/)).toBeNull();

    // Neighbours still render their own content.
    expect(screen.getByText("2 in flight")).toBeTruthy();
    expect(screen.getByText("Batman")).toBeTruthy();
    expect(screen.getByText("50.0%")).toBeTruthy();
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
                  ComicName: "Spider-Man",
                  Issue_Number: "1",
                  DateAdded: "2026-04-05T12:00:00",
                  Status: "Snatched",
                  Provider: "nzb",
                  ComicID: "1",
                  IssueID: "101",
                  ComicImage: null,
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
      expect(screen.getByText("Spider-Man #1")).toBeTruthy();
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

    await waitFor(() => {
      expect(screen.getByText(/library unavailable/)).toBeTruthy();
    });
    // All three tiles read the library, so all three report unavailable —
    // while the in-flight line, on its own endpoint, still answers.
    expect(screen.getAllByText("unavailable").length).toBe(3);
    expect(screen.getByText("2 in flight")).toBeTruthy();
    expect(screen.queryByText("50.0%")).toBeNull();
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

  it("renders the recent chats card", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Recent chats")).toBeTruthy();
    });
    expect(screen.getByRole("link", { name: "all →" })).toBeTruthy();
  });

  it("hands a typed question to the chat workspace", async () => {
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
    await user.click(
      screen.getByRole("button", { name: "Which runs have gaps?" }),
    );
    expect((ask as HTMLInputElement).value).toBe("Which runs have gaps?");

    await user.click(screen.getByRole("button", { name: "Ask Comicarr" }));
    await waitFor(() => {
      expect(screen.getByTestId("full-location").textContent).toBe(
        "/chat?q=Which%20runs%20have%20gaps%3F",
      );
    });
  });
});
