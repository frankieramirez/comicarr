import { describe, it, expect } from "vitest";
import {
  detectImportSearchMode,
  getImportGroupTypeLabel,
  getImportIssueLabel,
  getImportIssueRange,
} from "@/lib/importUtils";
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

  it("returns manga for folder groups with numeric chapter-only filenames", () => {
    const group = makeImportGroup({
      DynamicName: "folder:manga-a",
      files: [
        {
          impID: "1",
          ComicFilename: "001.cbz",
          ComicLocation: "/imports/Manga A/001.cbz",
          IssueNumber: "1",
          ComicYear: null,
          Status: "Unmatched",
          IgnoreFile: 0,
          MatchConfidence: null,
          SuggestedComicID: null,
          SuggestedComicName: null,
          SuggestedIssueID: null,
          MatchSource: null,
        },
        {
          impID: "2",
          ComicFilename: "002.cbz",
          ComicLocation: "/imports/Manga A/002.cbz",
          IssueNumber: "2",
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
    expect(getImportIssueLabel(group)).toBe("Chapter");
    expect(getImportIssueRange(group)).toBe("Chapters 1-2");
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

describe("import group review helpers", () => {
  it("labels folder and single-file groups from DynamicName", () => {
    expect(
      getImportGroupTypeLabel(
        makeImportGroup({ DynamicName: "folder:manga-a" }),
      ),
    ).toBe("Folder group");
    expect(
      getImportGroupTypeLabel(makeImportGroup({ DynamicName: "file:imp-1" })),
    ).toBe("Single file");
    expect(getImportGroupTypeLabel(makeImportGroup())).toBe("Review group");
  });

  it("uses chapter labels and ranges for manga-style groups", () => {
    const group = makeImportGroup({
      DynamicName: "folder:manga-a",
      files: [
        {
          impID: "1",
          ComicFilename: "chapter 2.cbz",
          ComicLocation: "/imports/manga-a/chapter 2.cbz",
          IssueNumber: "2",
          ComicYear: null,
          Status: "Unmatched",
          IgnoreFile: 0,
          MatchConfidence: null,
          SuggestedComicID: null,
          SuggestedComicName: null,
          SuggestedIssueID: null,
          MatchSource: null,
        },
        {
          impID: "2",
          ComicFilename: "chapter 1.cbz",
          ComicLocation: "/imports/manga-a/chapter 1.cbz",
          IssueNumber: "1",
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

    expect(getImportIssueLabel(group)).toBe("Chapter");
    expect(getImportIssueRange(group)).toBe("Chapters 1-2");
  });
});
