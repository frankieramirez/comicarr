import { describe, expect, it } from "vitest";
import { seriesSyncLabel } from "@/lib/series-utils";

describe("seriesSyncLabel", () => {
  it("uses LastUpdated as the last metadata refresh", () => {
    expect(
      seriesSyncLabel({
        LastUpdated: "2026-08-16 12:00:00",
        LatestDate: "Unknown",
      }),
    ).toBe("last sync 2026-08-16 12:00:00");
  });

  it("stays unsynced when LatestDate is only a release sentinel", () => {
    expect(
      seriesSyncLabel({
        LastUpdated: null,
        LatestDate: "Unknown",
      }),
    ).toBe("unsynced");
    expect(
      seriesSyncLabel({ LastUpdated: "   ", LatestDate: "2026-08-01" }),
    ).toBe("unsynced");
    expect(
      seriesSyncLabel({ LastUpdated: "Error", LatestDate: "2026-08-01" }),
    ).toBe("unsynced");
  });

  it("treats a missing refresh timestamp as unsynced", () => {
    expect(seriesSyncLabel({})).toBe("unsynced");
  });
});
