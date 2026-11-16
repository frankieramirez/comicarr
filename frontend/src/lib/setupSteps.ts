/**
 * The four steps between a fresh install and a first download, pure. The
 * dashboard shows them as "Finish setting up" until the library has a series
 * and every step is done.
 */

import type { Config } from "@/types/config";
import {
  SETTINGS_CLIENTS,
  SETTINGS_INDEXERS,
  type SearchBlocker,
} from "@/lib/searchBlockers";

export interface SetupStep {
  key: "library" | "comicvine" | "indexer" | "client";
  title: string;
  /** What the step is for, or what was set, once it is done. */
  detail: string;
  done: boolean;
  fix: { label: string; to: string };
}

/** `get_safe_config` sends an unset path as missing, but old installs say "None". */
function isSet(path: string | undefined | null): path is string {
  const value = (path ?? "").trim();
  return value !== "" && value.toLowerCase() !== "none";
}

export function setupSteps({
  config,
  blockers,
}: {
  config: Config | undefined;
  blockers: SearchBlocker[];
}): SetupStep[] {
  const library = config?.destination_dir;
  // A manga-only install never asks ComicVine anything.
  const comicvineNeeded = config?.comicvine_enabled !== false;
  const comicvineDone = !comicvineNeeded || Boolean(config?.comicvine_api_set);
  const missing = new Set(blockers.map((blocker) => blocker.key));

  return [
    {
      key: "library",
      title: "Library folder",
      detail: isSet(library)
        ? library
        : "Where Comicarr keeps your comics. New series folders go here.",
      done: isSet(library),
      fix: { label: "Choose a folder", to: "/settings?section=general" },
    },
    {
      key: "comicvine",
      title: "ComicVine API key",
      detail: comicvineDone
        ? comicvineNeeded
          ? "Saved"
          : "Not needed: ComicVine is off"
        : "Free from comicvine.gamespot.com. Needed to add series and fetch issues.",
      done: comicvineDone,
      fix: { label: "Add API key", to: "/settings?section=api" },
    },
    {
      key: "indexer",
      title: "Indexer",
      detail: missing.has("indexer")
        ? "Prowlarr, a Newznab or Torznab indexer, or GetComics."
        : "Ready to search",
      done: !missing.has("indexer"),
      fix: { label: "Add an indexer", to: SETTINGS_INDEXERS },
    },
    {
      key: "client",
      title: "Download client",
      detail: missing.has("client")
        ? "SABnzbd, NZBGet, qBittorrent, or another client."
        : "Ready to download",
      done: !missing.has("client"),
      fix: { label: "Add a download client", to: SETTINGS_CLIENTS },
    },
  ];
}
