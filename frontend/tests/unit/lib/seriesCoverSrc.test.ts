import { describe, expect, it } from "vitest";
import { seriesCoverSrc } from "@/lib/series-utils";

describe("seriesCoverSrc", () => {
  it("returns the cache-first art proxy for library ids", () => {
    expect(seriesCoverSrc("md-onepiece")).toBe("/api/metadata/art/md-onepiece");
    expect(seriesCoverSrc("mal-13")).toBe("/api/metadata/art/mal-13");
  });

  it("encodes the id and never emits a provider CDN", () => {
    const src = seriesCoverSrc("md-abc/../x");
    expect(src).toBe("/api/metadata/art/md-abc%2F..%2Fx");
    expect(src).not.toContain("uploads.mangadex.org");
  });

  it("returns null when there is no series id", () => {
    expect(seriesCoverSrc(null)).toBeNull();
    expect(seriesCoverSrc(undefined)).toBeNull();
    expect(seriesCoverSrc("")).toBeNull();
  });
});
