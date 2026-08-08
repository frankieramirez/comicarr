import { describe, expect, it } from "vitest";
import {
  DEFAULT_SEARCH_INTERVAL_MINUTES,
  healthBandView,
} from "@/lib/healthBand";
import type { AcquisitionHealthResponse } from "@/hooks/useAcquisitionHealth";

const NOW = Date.UTC(2026, 7, 8, 12, 0, 0);
const MINUTE = 60;

/** Epoch seconds, `minutes` before `NOW`. */
function minutesAgo(minutes: number): number {
  return NOW / 1000 - minutes * MINUTE;
}

/** Everything fine: one ready route, both indexers clear, the worker alive. */
function healthy(
  overrides: Partial<AcquisitionHealthResponse> = {},
): AcquisitionHealthResponse {
  return {
    viable_route: true,
    routes: {
      nzb: {
        ready: true,
        reason: "ready",
        downstream: "sabnzbd",
        providers: [
          {
            name: "nzbgeek",
            kind: "newznab",
            blocked: false,
            attempted: true,
            last_attempt: minutesAgo(10),
          },
          {
            name: "drunkenslug",
            kind: "newznab",
            blocked: false,
            attempted: true,
            last_attempt: minutesAgo(10),
          },
        ],
      },
      torrent: { ready: false, reason: "disabled", downstream: "disabled" },
    },
    workers: {
      search: { state: "idle", alive: true, healthy: true },
    },
    maintenance: { blocked: false },
    blocked_producer_count: 0,
    providers: [{ provider: "nzbgeek", lastrun: minutesAgo(10) }],
    ...overrides,
  };
}

function view(health: AcquisitionHealthResponse | null, interval?: number) {
  return healthBandView({
    health,
    searchIntervalMinutes: interval,
    now: NOW,
  });
}

function signal(
  result: ReturnType<typeof view>,
  key: "route" | "indexers" | "workers" | "gate" | "unknown",
) {
  return result.signals.find((item) => item.key === key);
}

describe("healthBandView", () => {
  describe("healthy", () => {
    it("reads as one quiet set of signals with no fix links", () => {
      const result = view(healthy());

      expect(result.tone).toBe("healthy");
      expect(result.unknown).toBe(false);
      expect(result.signals.map((item) => item.text)).toEqual([
        "SABnzbd ready",
        "2 of 2 indexers responding",
        "Search running",
      ]);
      expect(result.signals.every((item) => item.fix === undefined)).toBe(true);
    });

    it("stays silent about an open acquisition gate", () => {
      expect(signal(view(healthy()), "gate")).toBeUndefined();
    });

    it("names every ready route's downstream client", () => {
      const health = healthy();
      health.routes!.torrent = {
        ready: true,
        reason: "ready",
        downstream: "qbittorrent",
      };

      expect(signal(view(health), "route")!.text).toBe(
        "SABnzbd + qBittorrent ready",
      );
    });
  });

  describe("degraded", () => {
    it("names the specific worker that is not running", () => {
      const health = healthy({
        workers: {
          search: { alive: true },
          postprocess: { state: "stopped", alive: false },
        },
      });
      const result = view(health);

      expect(result.tone).toBe("degraded");
      expect(signal(result, "workers")).toMatchObject({
        tone: "degraded",
        text: "Post-processing worker not running",
      });
    });

    it("cannot claim liveness when no worker has ever reported one", () => {
      const result = view(healthy({ workers: {} }));

      expect(result.tone).toBe("degraded");
      expect(signal(result, "workers")!.text).toBe(
        "Cannot determine worker liveness",
      );
    });

    it("treats a failed worker projection as unknown, not as one dead worker", () => {
      const result = view(
        healthy({ workers: { unavailable: { state: "unavailable" } } }),
      );

      expect(signal(result, "workers")!.text).toBe(
        "Cannot determine worker liveness",
      );
    });

    it("counts some-but-not-all blocked indexers as degraded", () => {
      const health = healthy();
      health.routes!.nzb!.providers![0]!.blocked = true;
      const result = view(health);

      expect(result.tone).toBe("degraded");
      expect(signal(result, "indexers")).toMatchObject({
        tone: "degraded",
        text: "1 indexer unreachable",
      });
    });

    it("counts an indexer blocked on any route as one unreachable indexer", () => {
      const health = healthy();
      health.routes!.torrent = {
        ready: false,
        reason: "providers_temporarily_blocked",
        providers: [
          {
            name: "nzbgeek",
            kind: "newznab",
            blocked: true,
            attempted: true,
            last_attempt: null,
          },
        ],
      };

      expect(signal(view(health), "indexers")!.text).toBe(
        "1 indexer unreachable",
      );
    });

    it("reports a closed maintenance gate with its sanitized reason", () => {
      const result = view(
        healthy({
          maintenance: { blocked: true, reason: "repair token=do-not-render" },
        }),
      );

      expect(result.tone).toBe("degraded");
      expect(signal(result, "gate")!.text).toBe(
        "Paused for maintenance: repair token=[redacted]",
      );
      expect(signal(result, "gate")!.text).not.toContain("do-not-render");
    });

    it("reports deferred producers even while the gate is open", () => {
      const result = view(healthy({ blocked_producer_count: 2 }));

      expect(result.tone).toBe("degraded");
      expect(signal(result, "gate")!.text).toBe("2 producers deferred");
    });
  });

  describe("blocked", () => {
    it("names the nearest blocker and links to where the route is fixed", () => {
      const health = healthy({
        viable_route: false,
        routes: {
          nzb: {
            ready: false,
            reason: "client_not_ready",
            downstream: "sabnzbd",
          },
          torrent: { ready: false, reason: "disabled", downstream: "disabled" },
        },
      });
      const result = view(health);

      expect(result.tone).toBe("blocked");
      expect(signal(result, "route")).toMatchObject({
        tone: "blocked",
        text: "No usable download route — the download client is not configured",
        fix: { to: "/settings?section=clients" },
      });
    });

    it("prefers the blocker nearest to ready when routes disagree", () => {
      const result = view(
        healthy({
          viable_route: false,
          routes: {
            nzb: { ready: false, reason: "disabled" },
            torrent: { ready: false, reason: "path_not_ready" },
          },
        }),
      );

      expect(signal(result, "route")!.text).toBe(
        "No usable download route — the download directory is not reachable",
      );
    });

    it("is blocked, not degraded, when every indexer is unreachable", () => {
      const health = healthy();
      for (const provider of health.routes!.nzb!.providers!) {
        provider.blocked = true;
      }

      expect(signal(view(health), "indexers")!.tone).toBe("blocked");
      expect(view(health).tone).toBe("blocked");
    });

    it("refuses to call a route ready when nothing is", () => {
      const result = view(healthy({ viable_route: true, routes: {} }));

      expect(signal(result, "route")!.tone).toBe("blocked");
      expect(signal(result, "route")!.text).toBe("No usable download route");
    });
  });

  describe("unknown", () => {
    it("renders degraded when the endpoint could not be read", () => {
      const result = view(null);

      expect(result.tone).toBe("degraded");
      expect(result.unknown).toBe(true);
      expect(result.signals).toHaveLength(1);
      expect(result.signals[0]).toMatchObject({
        key: "unknown",
        tone: "degraded",
        text: "Cannot determine health",
      });
    });

    it("still reports a last-successful-search line, as unknown", () => {
      expect(view(null).lastSearch).toMatchObject({
        at: null,
        stale: true,
        text: "Last successful search: unknown",
      });
    });
  });

  describe("last successful search", () => {
    it("reads the newest provider run, whichever provider it came from", () => {
      const result = view(
        healthy({
          providers: [
            { provider: "a", lastrun: minutesAgo(600) },
            { provider: "b", lastrun: minutesAgo(12) },
          ],
        }),
      );

      expect(result.lastSearch.at).toBe(minutesAgo(12));
      expect(result.lastSearch.text).toBe("Last successful search: 12 minutes ago");
      expect(result.lastSearch.stale).toBe(false);
    });

    it("fails loud on absence rather than omitting the line", () => {
      const result = view(healthy({ providers: [] }));

      expect(result.lastSearch).toMatchObject({
        at: null,
        stale: true,
        text: "Last successful search: never",
      });
      expect(result.tone).toBe("degraded");
    });

    it("ignores a legacy zero or non-numeric lastrun", () => {
      const result = view(
        healthy({
          providers: [
            { provider: "a", lastrun: 0 },
            { provider: "b", lastrun: null },
          ],
        }),
      );

      expect(result.lastSearch.text).toBe("Last successful search: never");
    });

    it("degrades past 2× SEARCH_INTERVAL even when every component is fine", () => {
      const result = view(
        healthy({ providers: [{ provider: "a", lastrun: minutesAgo(11 * 1440) }] }),
        1440,
      );

      // The silent failure: nothing reports an error, and the pipeline has
      // produced nothing for eleven days.
      expect(result.signals.every((item) => item.tone === "healthy")).toBe(true);
      expect(result.lastSearch.stale).toBe(true);
      expect(result.lastSearch.text).toBe("Last successful search: 11 days ago");
      expect(result.tone).toBe("degraded");
    });

    it("scales the threshold with the configured interval", () => {
      const providers = [{ provider: "a", lastrun: minutesAgo(90) }];

      expect(view(healthy({ providers }), 30).lastSearch.stale).toBe(true);
      expect(view(healthy({ providers }), 120).lastSearch.stale).toBe(false);
    });

    it("falls back to the registry default for a nonsensical interval", () => {
      const providers = [{ provider: "a", lastrun: minutesAgo(1441) }];

      expect(view(healthy({ providers }), 0).lastSearch.stale).toBe(false);
      expect(
        view(healthy({ providers }), DEFAULT_SEARCH_INTERVAL_MINUTES).lastSearch
          .stale,
      ).toBe(false);
      expect(
        view(
          healthy({
            providers: [
              { provider: "a", lastrun: minutesAgo(2 * DEFAULT_SEARCH_INTERVAL_MINUTES + 1) },
            ],
          }),
          0,
        ).lastSearch.stale,
      ).toBe(true);
    });
  });
});
