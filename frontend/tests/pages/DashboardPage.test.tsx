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
    expect(screen.getByText("Queue")).toBeTruthy();
    expect(screen.getByText("10")).toBeTruthy();
    expect(screen.getByText("250")).toBeTruthy();
  });

  it("renders separate active queue and recent activity previews", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Active queue")).toBeTruthy();
      expect(screen.getByText("Recent activity")).toBeTruthy();
    });

    await waitFor(() => {
      expect(screen.getByText("Downloading")).toBeTruthy();
      expect(screen.getByText("Spider-Man 001.cbz")).toBeTruthy();
      expect(screen.getByText("Spider-Man #1")).toBeTruthy();
    });
    expect(screen.getAllByText(/ago$/).length).toBeGreaterThan(0);
    expect(
      screen.getByRole("link", { name: "open queue →" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "open history →" }),
    ).toBeTruthy();
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
      http.get("/api/dashboard/queue", () =>
        HttpResponse.json({ count: 0, items: [] }),
      ),
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
      expect(screen.getByText("queue is clear")).toBeTruthy();
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
    expect(screen.getByText("Spider-Man 001.cbz")).toBeTruthy();
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

    await user.click(await screen.findByRole("button", { name: /retry/ }));

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
    // The three library tiles report unavailable; the queue tile still counts.
    expect(screen.getAllByText("unavailable").length).toBe(3);
    expect(screen.getByText("2")).toBeTruthy();
    expect(screen.queryByText("50.0%")).toBeNull();
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
