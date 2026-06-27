import type { ImportGroup } from "@/types";

const MANGA_ID_PREFIXES = ["md-", "mal-"];
const MANGA_FILENAME_PATTERN = /\b(ch\.?|chapter)\s*\d+/i;
const NUMERIC_CHAPTER_FILENAME_PATTERN = /^\d+(?:\.\d+)?$/;

export type ImportSearchMode = "comic" | "manga";
export type ImportGroupType = "folder" | "file" | "unknown";

/**
 * Detect whether an import group should search manga or comic providers.
 */
export function detectImportSearchMode(
  importGroup: ImportGroup | null,
): ImportSearchMode {
  if (!importGroup) {
    return "comic";
  }

  const comicId = importGroup.SuggestedComicID || importGroup.ComicID;
  if (
    comicId &&
    MANGA_ID_PREFIXES.some((prefix) => comicId.startsWith(prefix))
  ) {
    return "manga";
  }

  if (
    importGroup.files?.some((file) =>
      MANGA_FILENAME_PATTERN.test(file.ComicFilename),
    )
  ) {
    return "manga";
  }

  if (hasFolderChapterContext(importGroup)) {
    return "manga";
  }

  return "comic";
}

export function getImportGroupType(
  importGroup: ImportGroup | null,
): ImportGroupType {
  const dynamicName = importGroup?.DynamicName ?? "";
  if (dynamicName.startsWith("folder:")) {
    return "folder";
  }
  if (dynamicName.startsWith("file:")) {
    return "file";
  }
  return "unknown";
}

export function getImportGroupTypeLabel(
  importGroup: ImportGroup | null,
): string {
  const groupType = getImportGroupType(importGroup);
  if (groupType === "folder") {
    return "Folder group";
  }
  if (groupType === "file") {
    return "Single file";
  }
  return "Review group";
}

export function getImportIssueLabel(importGroup: ImportGroup | null): string {
  return detectImportSearchMode(importGroup) === "manga" ? "Chapter" : "Issue";
}

function getFilenameStem(filename: string): string {
  return filename.replace(/\.[^/.]+$/, "").trim();
}

function hasFolderChapterContext(importGroup: ImportGroup): boolean {
  if (getImportGroupType(importGroup) !== "folder") {
    return false;
  }

  return Boolean(
    importGroup.files?.some((file) => {
      const issueNumber = file.IssueNumber?.trim();
      if (!issueNumber) {
        return false;
      }

      const filenameStem = getFilenameStem(file.ComicFilename);
      return (
        MANGA_FILENAME_PATTERN.test(file.ComicFilename) ||
        NUMERIC_CHAPTER_FILENAME_PATTERN.test(filenameStem)
      );
    }),
  );
}

function compareIssueValues(left: string, right: string): number {
  const leftNumber = Number(left);
  const rightNumber = Number(right);
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
    return leftNumber - rightNumber;
  }
  return left.localeCompare(right, undefined, { numeric: true });
}

export function getImportIssueRange(
  importGroup: ImportGroup | null,
): string | null {
  if (!importGroup?.files?.length) {
    return null;
  }

  const values = Array.from(
    new Set(
      importGroup.files
        .map((file) => file.IssueNumber?.trim())
        .filter((value): value is string => Boolean(value)),
    ),
  ).sort(compareIssueValues);

  if (values.length === 0) {
    return null;
  }

  const label = getImportIssueLabel(importGroup);
  if (values.length === 1) {
    return `${label} ${values[0]}`;
  }

  return `${label}s ${values[0]}-${values[values.length - 1]}`;
}
