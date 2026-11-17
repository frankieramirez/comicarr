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
import {
  connectionVerdict,
  type ConnectionVerdict,
} from "@/lib/connectionVerdict";
import type { ConnectionCheck } from "@/hooks/useAcquisitionHealth";

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

/**
 * A configured indexer or client counts as done only once it has answered a
 * connection check. Before that the step stays open and says so, and a failed
 * check shows its reason, so "Ready" is never shown for a host nobody reached.
 */
function connectionStep(
  verdict: ConnectionVerdict,
  ready: string,
): { done: boolean; detail: string } {
  switch (verdict.state) {
    case "none":
    case "ok":
      return { done: true, detail: ready };
    case "failed": {
      const { label, result } = verdict.row;
      return {
        done: false,
        detail: result
          ? t`${label} did not answer: ${result}`
          : t`${label} did not answer its connection check.`,
      };
    }
    case "unchecked": {
      const label = verdict.rows[0].label;
      return { done: false, detail: t`Saved. Checking that ${label} answers…` };
    }
  }
}

export function setupSteps({
  config,
  blockers,
  connections,
}: {
  config: Config | undefined;
  blockers: SearchBlocker[];
  /** The last connection checks; leave out to judge by configuration alone. */
  connections?: ConnectionCheck[];
}): SetupStep[] {
  const library = config?.destination_dir;
  // A manga-only install never asks ComicVine anything.
  const comicvineNeeded = config?.comicvine_enabled !== false;
  const comicvineDone = !comicvineNeeded || Boolean(config?.comicvine_api_set);
  const missing = new Set(blockers.map((blocker) => blocker.key));
  const indexer = connectionStep(
    connections
      ? connectionVerdict(connections, "indexers")
      : { state: "none" },
    t`Ready to search`,
  );
  const client = connectionStep(
    connections ? connectionVerdict(connections, "client") : { state: "none" },
    t`Ready to download`,
  );

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
        : indexer.detail,
      done: !missing.has("indexer") && indexer.done,
      fix: { label: t`Add an indexer`, to: SETTINGS_INDEXERS },
    },
    {
      key: "client",
      title: t`Download client`,
      detail: missing.has("client")
        ? t`SABnzbd, NZBGet, qBittorrent, or another client.`
        : client.detail,
      done: !missing.has("client") && client.done,
      fix: { label: t`Add a download client`, to: SETTINGS_CLIENTS },
    },
  ];
}
