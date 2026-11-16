import { t } from "@lingui/core/macro";
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
      title: t`Library folder`,
      detail: isSet(library)
        ? library
        : t`Where Comicarr keeps your comics. New series folders go here.`,
      done: isSet(library),
      fix: { label: t`Choose a folder`, to: "/settings?section=general" },
    },
    {
      key: "comicvine",
      title: t`ComicVine API key`,
      detail: comicvineDone
        ? comicvineNeeded
          ? t`Saved`
          : t`Not needed: ComicVine is off`
        : t`Free from comicvine.gamespot.com. Needed to add series and fetch issues.`,
      done: comicvineDone,
      fix: { label: t`Add API key`, to: "/settings?section=api" },
    },
    {
      key: "indexer",
      title: t`Indexer`,
      detail: missing.has("indexer")
        ? t`Prowlarr, a Newznab or Torznab indexer, or GetComics.`
        : t`Ready to search`,
      done: !missing.has("indexer"),
      fix: { label: t`Add an indexer`, to: SETTINGS_INDEXERS },
    },
    {
      key: "client",
      title: t`Download client`,
      detail: missing.has("client")
        ? t`SABnzbd, NZBGet, qBittorrent, or another client.`
        : t`Ready to download`,
      done: !missing.has("client"),
      fix: { label: t`Add a download client`, to: SETTINGS_CLIENTS },
    },
  ];
}
