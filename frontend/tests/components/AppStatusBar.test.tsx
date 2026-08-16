import { afterEach, describe, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { renderMinimal, screen } from "../test-utils";
import AppStatusBar from "@/components/layout/AppStatusBar";
import type { ServerEventsHealth } from "@/contexts/ServerEventsContext";

const { health } = vi.hoisted(() => ({
  health: { current: { live: "connected" } as ServerEventsHealth },
}));
vi.mock("@/contexts/ServerEventsContext", () => ({
  useServerEventsHealth: () => health.current,
}));

afterEach(() => {
  health.current = { live: "connected" };
});

describe("AppStatusBar", () => {
  it("shows library, api, and quiet in-flight counts", async () => {
    renderMinimal(<AppStatusBar />);

    await waitFor(() => {
      expect(screen.getByText("10 series")).toBeTruthy();
      expect(screen.getByText("online")).toBeTruthy();
      expect(screen.getByText("2 in flight")).toBeTruthy();
    });

    expect(screen.queryByText("2 active")).toBeNull();
    expect(screen.queryByText(/queue:/i)).toBeNull();
    expect(screen.queryByText("production")).toBeNull();
    expect(screen.queryByText("healthy")).toBeNull();

    // In-flight count links to the items it counts; library/api do not.
    const activityLink = screen.getByRole("link", { name: "2 in flight" });
    expect(activityLink.getAttribute("href")).toBe("/activity?state=in_flight");
    expect(screen.queryByRole("link", { name: /10 series/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /online/ })).toBeNull();

    // Outer row is not aria-live; dedicated polite region is.
    const status = screen.getByLabelText("Application status");
    expect(status.getAttribute("aria-live")).toBeNull();
    expect(status.querySelector("[aria-live='polite']")).toBeTruthy();
  });

  it("shows idle when open-work counts are empty", async () => {
    server.use(
      http.get("/api/activity/status", () =>
        HttpResponse.json({ in_flight: 0, attention: 0 }),
      ),
    );

    renderMinimal(<AppStatusBar />);

    await waitFor(() => {
      expect(screen.getByText("idle")).toBeTruthy();
    });
    expect(screen.queryByText(/in flight/)).toBeNull();
    expect(screen.queryByText(/need attention/)).toBeNull();
    expect(
      screen.getByRole("link", { name: "idle" }).getAttribute("href"),
    ).toBe("/activity");
  });

  it("shows attention segment only when K > 0", async () => {
    server.use(
      http.get("/api/activity/status", () =>
        HttpResponse.json({ in_flight: 3, attention: 2 }),
      ),
    );

    renderMinimal(<AppStatusBar />);

    await waitFor(() => {
      expect(screen.getByText("3 in flight")).toBeTruthy();
      expect(screen.getByText("⚠ 2 need attention")).toBeTruthy();
    });

    expect(
      screen
        .getByRole("link", { name: "⚠ 2 need attention" })
        .getAttribute("href"),
    ).toBe("/activity/attention");
  });

  it("shows unreachable after a prolonged live-channel loss", async () => {
    health.current = { live: "lost" };

    renderMinimal(<AppStatusBar />);

    await waitFor(() => {
      expect(screen.getByText("unreachable")).toBeTruthy();
    });
    // HTTP is fine; only the live channel is gone, so counts are suppressed.
    expect(screen.getByText("online")).toBeTruthy();
    expect(screen.queryByText(/in flight/)).toBeNull();
  });

  it("stays quiet while the live channel is merely reconnecting", async () => {
    health.current = { live: "reconnecting" };

    renderMinimal(<AppStatusBar />);

    await waitFor(() => {
      expect(screen.getByText("2 in flight")).toBeTruthy();
    });
    expect(screen.queryByText("unreachable")).toBeNull();
  });

  it("shows unreachable when library and api are both down", async () => {
    server.use(
      http.get("/api/dashboard/library", () =>
        HttpResponse.json({ detail: "Database unavailable" }, { status: 503 }),
      ),
      http.get("/api/health", () =>
        HttpResponse.json({ detail: "Service unavailable" }, { status: 503 }),
      ),
      http.get("/api/activity/status", () =>
        HttpResponse.json({ detail: "Status unavailable" }, { status: 503 }),
      ),
    );

    renderMinimal(<AppStatusBar />);

    await waitFor(() => {
      expect(screen.getByText("unavailable")).toBeTruthy();
      expect(screen.getByText("offline")).toBeTruthy();
      expect(screen.getByText("unreachable")).toBeTruthy();
    });

    expect(
      screen.getByRole("link", { name: "unreachable" }).getAttribute("href"),
    ).toBe("/activity");
  });
});
