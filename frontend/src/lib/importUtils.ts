import type { ImportGroup } from "@/types";

const MANGA_ID_PREFIXES = ["md-", "mal-"];
const MANGA_FILENAME_PATTERN = /\b(ch\.?|chapter)\s*\d+/i;

export type ImportSearchMode = "comic" | "manga";

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

  return "comic";
}
