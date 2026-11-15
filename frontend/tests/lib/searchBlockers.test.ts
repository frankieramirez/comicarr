import { describe, expect, it } from "vitest";
import { searchBlockers, searchPausedReason } from "@/lib/searchBlockers";
import { UNCONFIGURED_SEARCH_HEALTH } from "../mocks/searchHealth";

const keys = (health: Parameters<typeof searchBlockers>[0]) =>
  searchBlockers(health).map((blocker) => blocker.key);

describe("searchBlockers", () => {
  it("names both setup gaps on an install with no indexer and no client", () => {
    const blockers = searchBlockers(UNCONFIGURED_SEARCH_HEALTH);
    expect(blockers.map((b) => b.key)).toEqual(["indexer", "client"]);
    expect(blockers[0].fix).toEqual({
      label: "Add an indexer",
      to: "/settings?section=search",
    });
    expect(blockers[1].fix).toEqual({
      label: "Add a download client",
      to: "/settings?section=clients",
    });
    expect(searchPausedReason(blockers)).toBe("no indexer");
  });

  it("is empty once any route is ready", () => {
    expect(keys({ ...UNCONFIGURED_SEARCH_HEALTH, viable_route: true })).toEqual(
      [],
    );
  });

  it("is empty while health is unknown, so screens keep their wording", () => {
    expect(keys(null)).toEqual([]);
    expect(keys(undefined)).toEqual([]);
    expect(keys({})).toEqual([]);
    expect(searchPausedReason([])).toBeNull();
  });

  it("asks only for a client once an indexer exists", () => {
    const routes = UNCONFIGURED_SEARCH_HEALTH.routes!;
    const blockers = searchBlockers({
      ...UNCONFIGURED_SEARCH_HEALTH,
      routes: {
        ...routes,
        nzb: { ...routes.nzb, configured_provider_count: 1 },
      },
    });
    expect(blockers.map((b) => b.key)).toEqual(["client"]);
    expect(searchPausedReason(blockers)).toBe("no download client");
  });

  it("leaves a chosen but broken client to the health band", () => {
    const routes = UNCONFIGURED_SEARCH_HEALTH.routes!;
    expect(
      keys({
        ...UNCONFIGURED_SEARCH_HEALTH,
        routes: {
          ...routes,
          nzb: {
            ...routes.nzb,
            enabled: true,
            downstream: "sabnzbd",
            reason: "client_not_ready",
            configured_provider_count: 2,
          },
        },
      }),
    ).toEqual([]);
  });

  it("needs no client for direct downloads", () => {
    const routes = UNCONFIGURED_SEARCH_HEALTH.routes!;
    expect(
      keys({
        ...UNCONFIGURED_SEARCH_HEALTH,
        routes: {
          ...routes,
          ddl: { ...routes.ddl, enabled: true, configured_provider_count: 1 },
        },
      }),
    ).toEqual([]);
  });
});
