/**
 * The folders Import scans, pure. Mirrors `library_scan_dir` in
 * `comicarr/app/common/library_roots.py`: a comic scan falls back to the
 * library folder, and a manga scan falls back to the manga library folder
 * only, never to the comic one.
 */

import type { Config } from "@/types/config";

/** Where library folders are set in Settings. */
export const SETTINGS_FOLDERS = "/settings?section=media";

function folder(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const path = value.trim();
  return path === "" || path.toLowerCase() === "none" ? undefined : path;
}

export function libraryScanFolders(config: Config | undefined): {
  comic?: string;
  manga?: string;
} {
  return {
    comic: folder(config?.comic_dir) ?? folder(config?.destination_dir),
    manga: folder(config?.manga_dir) ?? folder(config?.manga_destination_dir),
  };
}
