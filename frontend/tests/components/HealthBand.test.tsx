import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { renderMinimal, screen, waitFor } from "../test-utils";
import HealthBand from "@/components/dashboard/HealthBand";

const MINUTE_MS = 60_000;

/** Epoch seconds, `minutes` before now — the shape `provider_searches` stores. */
function minutesAgo(minutes: number): number {
  return Math.floor((Date.now() - minutes * MINUTE_MS) / 1000);
}

function installHealth(payload: unknown) {
  server.use(http.get("/api/search/health", () => HttpResponse.json(payload)));
}

/** `SEARCH_INTERVAL` in minutes, so a test can place a run either side of 2×. */
function installConfig(searchInterval: number) {
  server.use(
    http.get("/api/config", () =>
      HttpResponse.json({ search_interval: searchInterval }),
    ),
  );
}

const healthyPayload = {
  viable_route: true,
  routes: {
    nzb: {
      ready: true,
      reason: "ready",
      downstream: "sabnzbd",
      providers: [
        { name: "nzbgeek", kind: "newznab", blocked: false, attempted: true },
        { name: "drunkenslug", kind: "newznab", blocked: false, attempted: true },
      ],
    },
  },
  workers: { search: { state: "idle", alive: true, healthy: true } },
  maintenance: { blocked: false },
  blocked_producer_count: 0,
  providers: [{ provider: "nzbgeek", lastrun: minutesAgo(12) }],
};

/** The band once its queries have answered, whatever they answered. */
async function band(): Promise<HTMLElement> {
  return await screen.findByRole("region", { name: "Acquisition health" });
}

describe("HealthBand", () => {
  it("renders healthy as one quiet line above the last-successful-search", async () => {
    installHealth(healthyPayload);
    installConfig(1440);

    renderMinimal(<HealthBand />);

    expect((await band()).getAttribute("data-tone")).toBe("healthy");
    expect(
      screen.getByText(
        "SABnzbd ready · 2 of 2 indexers responding · Search running",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText("Last successful search: 12 minutes ago"),
    ).toBeTruthy();
  });

  it("names the degraded component and keeps the healthy ones quiet", async () => {
    installHealth({
      ...healthyPayload,
      workers: {
        search: { alive: true },
        postprocess: { state: "stopped", alive: false },
      },
    });
    installConfig(1440);

    renderMinimal(<HealthBand />);

    expect((await band()).getAttribute("data-tone")).toBe("degraded");
    expect(screen.getByText("Post-processing worker not running")).toBeTruthy();
    expect(screen.getByText(/SABnzbd ready · 2 of 2 indexers responding/)).toBeTruthy();
  });

  it("links a blocked route to where it is fixed", async () => {
    installHealth({
      ...healthyPayload,
      viable_route: false,
      routes: {
        nzb: { ready: false, reason: "client_not_ready", downstream: "sabnzbd" },
      },
    });
    installConfig(1440);

    renderMinimal(<HealthBand />);

    expect((await band()).getAttribute("data-tone")).toBe("blocked");
    expect(
      screen.getByText(
        "No usable download route — the download client is not configured",
      ),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "open download clients →" })
        .getAttribute("href"),
    ).toBe("/settings?section=clients");
  });

  it("renders degraded, not healthy and not absent, when the endpoint fails", async () => {
    server.use(
      http.get("/api/search/health", () => new HttpResponse(null, { status: 500 })),
    );
    installConfig(1440);

    renderMinimal(<HealthBand />);

    expect((await band()).getAttribute("data-tone")).toBe("degraded");
    expect(screen.getByText("Cannot determine health")).toBeTruthy();
    // Absence of evidence is never health, and the load-bearing line still shows.
    expect(screen.queryByText(/indexers responding/)).toBeNull();
    expect(screen.getByText("Last successful search: unknown")).toBeTruthy();
  });

  it("degrades on a stale last successful search while every component reports fine", async () => {
    installHealth({
      ...healthyPayload,
      providers: [{ provider: "nzbgeek", lastrun: minutesAgo(11 * 1440) }],
    });
    installConfig(1440);

    renderMinimal(<HealthBand />);

    expect((await band()).getAttribute("data-tone")).toBe("degraded");
    expect(screen.getByText("Last successful search: 11 days ago")).toBeTruthy();
    // No component complained. The band says so anyway — the silent failure.
    expect(
      screen.getByText(
        "SABnzbd ready · 2 of 2 indexers responding · Search running",
      ),
    ).toBeTruthy();
  });

  it("never hides the last-successful-search line, even having never run", async () => {
    installHealth({ ...healthyPayload, providers: [] });
    installConfig(1440);

    renderMinimal(<HealthBand />);

    expect((await band()).getAttribute("data-tone")).toBe("degraded");
    expect(screen.getByText("Last successful search: never")).toBeTruthy();
  });

  it("occupies its final position while loading, rather than popping in", async () => {
    installHealth(healthyPayload);
    installConfig(1440);

    renderMinimal(<HealthBand />);

    expect(screen.getByTestId("health-band-loading")).toBeTruthy();
    await waitFor(() =>
      expect(screen.queryByTestId("health-band-loading")).toBeNull(),
    );
  });
});
