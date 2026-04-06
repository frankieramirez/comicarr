/**
 * Tests for the DashboardPage component.
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

  it("renders collection stats", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Active Series")).toBeTruthy();
      expect(screen.getByText("Issues Collected")).toBeTruthy();
      expect(screen.getByText("Completion")).toBeTruthy();
    });

    expect(screen.getByText("10")).toBeTruthy();
    expect(screen.getByText("250")).toBeTruthy();
    expect(screen.getByText("50%")).toBeTruthy();
  });

  it("renders recent downloads section", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Recent Downloads")).toBeTruthy();
      expect(screen.getByText("Spider-Man")).toBeTruthy();
    });
  });

  it("renders upcoming releases section", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Upcoming This Week")).toBeTruthy();
      expect(screen.getByText("Batman")).toBeTruthy();
    });
  });

  it("shows discovery banner when AI is not configured", async () => {
    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("AI Features Available")).toBeTruthy();
    });
  });

  it("shows AI activity panel when AI is configured", async () => {
    server.use(
      http.get("/api/dashboard", () => {
        return HttpResponse.json({
          recently_downloaded: [],
          upcoming_releases: [],
          stats: {
            total_series: 5,
            total_issues: 100,
            total_expected: 200,
            completion_pct: 50.0,
          },
          ai_activity: [
            {
              timestamp: "2026-04-05T12:00:00",
              feature_type: "search",
              action_description: "Expanded search query",
              prompt_tokens: 100,
              completion_tokens: 50,
              success: true,
            },
          ],
          ai_configured: true,
        });
      }),
    );

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("AI Activity")).toBeTruthy();
      expect(screen.getByText("Expanded search query")).toBeTruthy();
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
      expect(screen.getByText("No recent downloads")).toBeTruthy();
      expect(
        screen.getByText("No upcoming releases this week"),
      ).toBeTruthy();
    });
  });

  it("hides discovery banner when dismissed", async () => {
    localStorage.setItem("dismissed_ai_banner", "true");

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText("Dashboard")).toBeTruthy();
    });

    expect(screen.queryByText("AI Features Available")).toBeNull();
  });
});
