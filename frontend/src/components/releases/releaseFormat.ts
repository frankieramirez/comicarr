import { t } from "@lingui/core/macro";
/**
 * The format chips on Releases (#1383). Comics come from the weekly pull
 * source; manga, manhwa and manhua from MangaUpdates. A library series only
 * knows comic vs manga, so the library view folds the three manga formats
 * into one chip.
 */
export type ReleaseFormat = "all" | "comics" | "manga" | "manhwa" | "manhua";

export const FORMAT_LABEL = (): Record<ReleaseFormat, string> => ({
  all: t`All`,
  comics: t`Comics`,
  manga: t`Manga`,
  manhwa: t`Manhwa`,
  manhua: t`Manhua`,
});

export const INDUSTRY_FORMATS: ReleaseFormat[] = [
  "all",
  "comics",
  "manga",
  "manhwa",
  "manhua",
];

export const LIBRARY_FORMATS: ReleaseFormat[] = ["all", "comics", "manga"];

export function isMangaFormat(format: ReleaseFormat): boolean {
  return format === "manga" || format === "manhwa" || format === "manhua";
}

/** The chip a format falls back to where manhwa and manhua are not told apart. */
export function libraryFormat(format: ReleaseFormat): ReleaseFormat {
  return isMangaFormat(format) ? "manga" : format;
}

const KEYS = {
  libraryOnly: "comicarr.releases.libraryOnly",
  popularOnly: "comicarr.releases.popularOnly",
  format: "comicarr.releases.format",
} as const;

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Private windows and blocked storage just forget the choice.
  }
}

/** Remembered toggles; each defaults to on when nothing is stored. */
export const releasePrefs = {
  libraryOnly: () => read(KEYS.libraryOnly) !== "0",
  setLibraryOnly: (value: boolean) =>
    write(KEYS.libraryOnly, value ? "1" : "0"),
  popularOnly: () => read(KEYS.popularOnly) !== "0",
  setPopularOnly: (value: boolean) =>
    write(KEYS.popularOnly, value ? "1" : "0"),
  format: (): ReleaseFormat => {
    const stored = read(KEYS.format);
    return INDUSTRY_FORMATS.includes(stored as ReleaseFormat)
      ? (stored as ReleaseFormat)
      : "all";
  },
  setFormat: (value: ReleaseFormat) => write(KEYS.format, value),
};
