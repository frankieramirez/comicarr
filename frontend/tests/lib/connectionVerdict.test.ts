import { describe, expect, it } from "vitest";
import {
  DEFAULT_SEARCH_INTERVAL_MINUTES,
  healthBandView,
} from "@/lib/healthBand";
import { connectionVerdict } from "@/lib/connectionVerdict";
import { setupSteps } from "@/lib/setupSteps";
import type {
  AcquisitionHealthResponse,
  ConnectionCheck,
} from "@/hooks/useAcquisitionHealth";

const NOW = Date.UTC(2026, 10, 17, 12, 0, 0);

function row(overrides: Partial<ConnectionCheck>): ConnectionCheck {
  return {
    key: "sabnzbd",
    label: "SABnzbd",
    kind: "client",
    route: "nzb",
    checked_at: null,
    ok: null,
    result: null,
    latency_ms: null,
    latency_label: null,
    version: null,
    active: null,
    ...overrides,
  };
}

const INDEXERS = (overrides: Partial<ConnectionCheck> = {}) =>
  row({
    key: "indexers",
    label: "Indexers",
    kind: "indexers",
    route: null,
    count: 1,
    ...overrides,
  });

/** Configured and not blocked: what acquisition health alone calls ready. */
const CONFIGURED: AcquisitionHealthResponse = {
  viable_route: true,
  routes: {
    nzb: {
      ready: true,
      reason: "ready",
      downstream: "sabnzbd",
      providers: [{ name: "indexer", kind: "newznab", blocked: false }],
    },
  },
  workers: { search: { state: "idle", alive: true, healthy: true } },
  maintenance: { blocked: false },
  blocked_producer_count: 0,
  providers: [{ provider: "indexer", lastrun: NOW / 1000 - 600 }],
};

function band(connections: ConnectionCheck[] | undefined) {
  return healthBandView({
    health: CONFIGURED,
    connections,
    searchIntervalMinutes: DEFAULT_SEARCH_INTERVAL_MINUTES,
    now: NOW,
  });
}

describe("connectionVerdict", () => {
  it("is ok once any connection of the kind answered", () => {
    expect(
      connectionVerdict(
        [row({ ok: false }), row({ key: "qbittorrent", ok: true })],
        "client",
      ).state,
    ).toBe("ok");
  });

  it("names the failure when none answered", () => {
    const verdict = connectionVerdict(
      [row({ ok: false, result: "Couldn't reach SABnzbd" })],
      "client",
    );
    expect(verdict).toMatchObject({ state: "failed" });
  });

  it("is unchecked before the first answer, and none when nothing can be checked", () => {
    expect(connectionVerdict([row({})], "client").state).toBe("unchecked");
    expect(connectionVerdict([row({})], "indexers").state).toBe("none");
  });
});

describe("setup steps and the health band wait for a real answer", () => {
  it("never says Ready for a client whose check failed", () => {
    const connections = [
      row({ ok: false, result: "Couldn't reach SABnzbd" }),
      INDEXERS({ ok: true }),
    ];
    const steps = setupSteps({ config: {}, blockers: [], connections });
    expect(steps[2]).toMatchObject({ done: true, detail: "Ready to search" });
    expect(steps[3]).toMatchObject({
      done: false,
      detail: "SABnzbd did not answer: Couldn't reach SABnzbd",
    });

    const route = band(connections).signals.find((s) => s.key === "route")!;
    expect(route).toMatchObject({
      tone: "blocked",
      text: "SABnzbd not answering — Couldn't reach SABnzbd",
      fix: { to: "/settings?section=clients" },
    });
  });

  it("says not checked yet instead of Ready before the first check", () => {
    const connections = [row({}), INDEXERS({})];
    const steps = setupSteps({ config: {}, blockers: [], connections });
    expect(steps[2].done).toBe(false);
    expect(steps[3]).toMatchObject({
      done: false,
      detail:
        "Set up. Waiting for its first connection check, which runs within a few minutes.",
    });

    const texts = band(connections).signals.map((s) => s.text);
    expect(texts).toContain("SABnzbd set up, not checked yet");
    expect(texts).toContain("Indexers set up, not checked yet");
  });

  it("keeps Ready once both answered", () => {
    const connections = [row({ ok: true }), INDEXERS({ ok: true })];
    const steps = setupSteps({ config: {}, blockers: [], connections });
    expect(steps.slice(2).every((s) => s.done)).toBe(true);
    expect(band(connections).tone).toBe("healthy");
  });

  it("reports indexer failures with the check's own words", () => {
    const signal = band([
      row({ ok: true }),
      INDEXERS({
        ok: false,
        result: "indexer answered with HTTP 401",
        responding: 0,
      }),
    ]).signals.find((s) => s.key === "indexers")!;
    expect(signal).toMatchObject({
      tone: "blocked",
      text: "Indexers not answering — indexer answered with HTTP 401",
    });
  });
});
