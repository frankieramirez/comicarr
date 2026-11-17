import { describe, expect, it } from "vitest";
import { searchBlockers } from "@/lib/searchBlockers";
import { setupSteps } from "@/lib/setupSteps";
import { UNCONFIGURED_SEARCH_HEALTH } from "../mocks/searchHealth";

const blockers = searchBlockers(UNCONFIGURED_SEARCH_HEALTH);

describe("setupSteps", () => {
  it("lists the four steps to a first download, in order", () => {
    const steps = setupSteps({ config: {}, blockers });
    expect(steps.map((s) => [s.key, s.done])).toEqual([
      ["library", false],
      ["comicvine", false],
      ["indexer", false],
      ["client", false],
    ]);
    expect(steps.map((s) => s.fix.to)).toEqual([
      "/settings?section=media",
      "/settings?section=api",
      "/settings?section=search",
      "/settings?section=clients",
    ]);
  });

  it("shows the chosen folder once it is set, and treats 'None' as unset", () => {
    const set = setupSteps({
      config: { destination_dir: "/data/comics" },
      blockers,
    });
    expect(set[0]).toMatchObject({ done: true, detail: "/data/comics" });
    expect(
      setupSteps({ config: { destination_dir: "None" }, blockers })[0].done,
    ).toBe(false);
  });

  it("needs no ComicVine key on a manga-only install", () => {
    const [, comicvine] = setupSteps({
      config: { comicvine_enabled: false },
      blockers,
    });
    expect(comicvine).toMatchObject({ done: true });
    expect(
      setupSteps({ config: { comicvine_api_set: true }, blockers })[1].done,
    ).toBe(true);
  });

  it("marks indexer and client done once health has no gaps", () => {
    const steps = setupSteps({ config: {}, blockers: [] });
    expect(steps[2].done).toBe(true);
    expect(steps[3].done).toBe(true);
  });
});
