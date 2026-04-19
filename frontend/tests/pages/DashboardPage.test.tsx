/**
 * Tests for the DashboardPage component (Direction B redesign).
 *
 * Uses getByText / queryByText which throw or return null respectively.
 * No @testing-library/jest-dom needed.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { waitFor } from "@testing-library/react";
import { server } from "../mocks/server";
import { http, HttpResponse } from "msw";
import { render, screen } from "../test-utils";
import DashboardPage from "@/pages/DashboardPage";

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

  it("renders queue & recent activity section", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Queue & recent activity")).toBeTruthy();
    });

    // Activity row title is "<ComicName> #<Issue_Number>" inside a Link.
    await waitFor(() => {
      expect(screen.getByText("Spider-Man #1")).toBeTruthy();
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
      http.get("/api/dashboard", () => {
        return HttpResponse.json({
          recently_downloaded: [],
          upcoming_releases: [],
          stats: {
            total_series: 0,
            total_issues: 0,
            total_expected: 0,
            completion_pct: 0,
          },
          ai_activity: [],
          ai_configured: false,
        });
      }),
    );

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("no recent activity")).toBeTruthy();
      expect(screen.getByText("nothing upcoming this week")).toBeTruthy();
    });
  });

  it("renders command hint card", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText(/COMMAND HINT/)).toBeTruthy();
    });
  });
});
