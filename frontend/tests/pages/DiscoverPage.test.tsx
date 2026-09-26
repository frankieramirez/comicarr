import { describe, expect, it } from "vitest";
import { fireEvent } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { createTestQueryClient, render, screen, waitFor } from "../test-utils";
import DiscoverPage from "@/pages/DiscoverPage";
import type { SeriesRecommendation } from "@/hooks/useAiRecommendations";

const recommendation: SeriesRecommendation = {
  comic_name: "Saga",
  publisher: "Image",
  reason: "A story you may enjoy",
  because_of: "Monstress",
  comicid: "c1",
  comicyear: "2012",
  issues: 72,
  comicimage: null,
};

function configuredStatus() {
  return http.get("/api/ai/status", () =>
    HttpResponse.json({ configured: true, circuit_state: "closed" }),
  );
}

function recommendations(items: SeriesRecommendation[] = [recommendation]) {
  return http.get("/api/ai/recommendations", () =>
    HttpResponse.json({ recommendations: items }),
  );
}

describe("DiscoverPage", () => {
  it("shows a retry action when AI status fails instead of loading forever", async () => {
    let requests = 0;
    server.use(
      http.get("/api/ai/status", () => {
        requests += 1;
        return requests === 1
          ? HttpResponse.json({ detail: "unavailable" }, { status: 503 })
          : HttpResponse.json({ configured: false });
      }),
    );

    render(<DiscoverPage />);
    expect(await screen.findByText("Failed to check AI status")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Connect an AI provider")).toBeTruthy();
    expect(requests).toBe(2);
  });

  it("hides cached cards after refresh failure, then restores them on retry", async () => {
    let requests = 0;
    server.use(
      configuredStatus(),
      recommendations(),
      http.post("/api/ai/recommendations/refresh", () => {
        requests += 1;
        return requests === 1
          ? HttpResponse.json({ detail: "model failed" }, { status: 503 })
          : HttpResponse.json({ recommendations: [recommendation] });
      }),
    );
    const queryClient = createTestQueryClient();
    render(<DiscoverPage />, { queryClient });
    expect(await screen.findByText("Saga")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(
      (await screen.findAllByText("Failed to refresh recommendations")).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText("Saga")).toBeNull();
    expect(queryClient.getQueryData(["ai", "recommendations"])).toEqual({
      recommendations: [recommendation],
    });

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Saga")).toBeTruthy();
    expect(requests).toBe(2);
  });

  it("blocks duplicate empty-state generation while a refresh is pending", async () => {
    let requests = 0;
    let finish: (() => void) | undefined;
    const pending = new Promise<void>((resolve) => {
      finish = resolve;
    });
    server.use(
      configuredStatus(),
      recommendations([]),
      http.post("/api/ai/recommendations/refresh", async () => {
        requests += 1;
        await pending;
        return HttpResponse.json({ recommendations: [] });
      }),
    );
    render(<DiscoverPage />);
    const generate = await screen.findByRole("button", {
      name: /Generate recommendations/,
    });
    fireEvent.click(generate);
    fireEvent.click(generate);
    await waitFor(() => expect(requests).toBe(1));
    expect(
      screen.queryByRole("button", { name: /Generate recommendations/ }),
    ).toBeNull();
    finish?.();
  });

  it("removes queued additions and restores one when import completion fails", async () => {
    server.use(
      configuredStatus(),
      recommendations(),
      http.post("/api/search/add", () => HttpResponse.json({ comicid: "c1" })),
    );
    const queryClient = createTestQueryClient();
    render(<DiscoverPage />, { queryClient });
    expect(await screen.findByText("Saga")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(screen.queryByText("Saga")).toBeNull());
    expect(queryClient.getQueryData(["ai", "recommendations"])).toEqual({
      recommendations: [],
    });

    window.dispatchEvent(
      new CustomEvent("comic-added", {
        detail: JSON.stringify({
          comicid: "c1",
          comicname: "Saga",
          status: "failure",
          message: "Import failed",
        }),
      }),
    );
    expect(await screen.findByText("Saga")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add" })).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(screen.queryByText("Saga")).toBeNull());
    window.dispatchEvent(
      new CustomEvent("comic-added", {
        detail: JSON.stringify({
          comicid: "c1",
          comicname: "Saga",
          status: "success",
          message: "Added",
        }),
      }),
    );
    expect(queryClient.getQueryData(["ai", "recommendations"])).toEqual({
      recommendations: [],
    });
  });

  it("refetches queued recommendations after leaving Discover", async () => {
    let recommendationFetches = 0;
    server.use(
      configuredStatus(),
      http.get("/api/ai/recommendations", () => {
        recommendationFetches += 1;
        return HttpResponse.json({ recommendations: [recommendation] });
      }),
      http.post("/api/search/add", () => HttpResponse.json({ comicid: "c1" })),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: Infinity } },
    });
    const view = render(<DiscoverPage />, { queryClient });
    expect(await screen.findByText("Saga")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(screen.queryByText("Saga")).toBeNull());

    view.unmount();
    window.dispatchEvent(
      new CustomEvent("comic-added", {
        detail: JSON.stringify({
          comicid: "c1",
          comicname: "Saga",
          status: "failure",
          message: "Import failed",
        }),
      }),
    );
    render(<DiscoverPage />, { queryClient });
    expect(await screen.findByText("Saga")).toBeTruthy();
    expect(recommendationFetches).toBeGreaterThan(1);
  });
});
