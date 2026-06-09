import { describe, it, expect } from "vitest";
import { detectImportSearchMode } from "@/lib/importUtils";
import type { ImportGroup } from "@/types";

function makeImportGroup(overrides: Partial<ImportGroup> = {}): ImportGroup {
  return {
    DynamicName: "test-series",
    ComicName: "Test Series",
    Volume: null,
    ComicYear: null,
    FileCount: 1,
    Status: "Unmatched",
    SRID: null,
    ComicID: null,
    MatchConfidence: null,
    SuggestedComicID: null,
    SuggestedComicName: null,
    files: [],
    ...overrides,
  };
}

describe("detectImportSearchMode", () => {
  it("returns manga for MangaDex suggested ID", () => {
    const group = makeImportGroup({ SuggestedComicID: "md-abc123" });
    expect(detectImportSearchMode(group)).toBe("manga");
  });

  it("returns manga for MAL comic ID", () => {
    const group = makeImportGroup({ ComicID: "mal-42" });
    expect(detectImportSearchMode(group)).toBe("manga");
  });

  it("returns manga for chapter-style filenames", () => {
    const group = makeImportGroup({
      files: [
        {
          impID: "1",
          ComicFilename: "One Piece Ch. 100.cbz",
          ComicLocation: "/imports/one-piece.cbz",
          IssueNumber: null,
          ComicYear: null,
          Status: "Unmatched",
          IgnoreFile: 0,
          MatchConfidence: null,
          SuggestedComicID: null,
          SuggestedComicName: null,
          SuggestedIssueID: null,
          MatchSource: null,
        },
      ],
    });
    expect(detectImportSearchMode(group)).toBe("manga");
  });

  it("defaults to comic when no manga signals are present", () => {
    const group = makeImportGroup({
      ComicID: "4050-12345",
      files: [
        {
          impID: "1",
          ComicFilename: "Amazing Spider-Man 001.cbz",
          ComicLocation: "/imports/asm.cbz",
          IssueNumber: "1",
          ComicYear: "2020",
          Status: "Unmatched",
          IgnoreFile: 0,
          MatchConfidence: null,
          SuggestedComicID: null,
          SuggestedComicName: null,
          SuggestedIssueID: null,
          MatchSource: null,
        },
      ],
    });
    expect(detectImportSearchMode(group)).toBe("comic");
  });

  it("returns comic for null import group", () => {
    expect(detectImportSearchMode(null)).toBe("comic");
  });
});
