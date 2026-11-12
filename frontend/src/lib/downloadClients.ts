import type {
  ReadableConfig,
  SettingsFormData,
} from "@/types/config.generated";

/**
 * Comicarr sends each kind of release to one client: one usenet client
 * (NZB_DOWNLOADER), one torrent client (TORRENT_DOWNLOADER, switched on by
 * ENABLE_TORRENTS) and the built-in direct downloader (ENABLE_DDL). These
 * helpers read that model back as the cards the Settings page shows.
 */
export type ClientKind = "usenet" | "torrent" | "ddl";

export type ClientId =
  | "sabnzbd"
  | "nzbget"
  | "blackhole"
  | "watchdir"
  | "utorrent"
  | "rtorrent"
  | "transmission"
  | "deluge"
  | "qbittorrent"
  | "ddl";

export interface ClientInfo {
  id: ClientId;
  kind: ClientKind;
  label: string;
  /** NZB_DOWNLOADER / TORRENT_DOWNLOADER value; null for DDL. */
  code: number | null;
  /** Its connection settings can be edited here; the rest live in config.ini. */
  editable: boolean;
}

export const CLIENTS: ClientInfo[] = [
  { id: "sabnzbd", kind: "usenet", label: "SABnzbd", code: 0, editable: true },
  { id: "nzbget", kind: "usenet", label: "NZBGet", code: 1, editable: true },
  {
    id: "blackhole",
    kind: "usenet",
    label: "Blackhole folder",
    code: 2,
    editable: false,
  },
  {
    id: "qbittorrent",
    kind: "torrent",
    label: "qBittorrent",
    code: 5,
    editable: true,
  },
  { id: "deluge", kind: "torrent", label: "Deluge", code: 4, editable: true },
  {
    id: "transmission",
    kind: "torrent",
    label: "Transmission",
    code: 3,
    editable: true,
  },
  {
    id: "rtorrent",
    kind: "torrent",
    label: "rTorrent",
    code: 2,
    editable: false,
  },
  {
    id: "utorrent",
    kind: "torrent",
    label: "uTorrent",
    code: 1,
    editable: false,
  },
  {
    id: "watchdir",
    kind: "torrent",
    label: "Watch folder",
    code: 0,
    editable: false,
  },
  {
    id: "ddl",
    kind: "ddl",
    label: "Direct downloads",
    code: null,
    editable: false,
  },
];

export const KIND_BADGE: Record<ClientKind, string> = {
  usenet: "Usenet",
  torrent: "Torrent",
  ddl: "DDL",
};

export const DDL_HOSTS = "GetComics · Mega · MediaFire · Pixeldrain";

export function clientById(id: ClientId): ClientInfo {
  return CLIENTS.find((client) => client.id === id) ?? CLIENTS[0];
}

function byCode(kind: ClientKind, code: number): ClientInfo | undefined {
  return CLIENTS.find((client) => client.kind === kind && client.code === code);
}

type Values = SettingsFormData & Partial<ReadableConfig>;

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/** The host line a card shows under the client's name. */
export function clientHost(id: ClientId, values: Values): string | null {
  switch (id) {
    case "sabnzbd":
      return text(values.sab_host) || null;
    case "nzbget": {
      const host = text(values.nzbget_host);
      const port = text(values.nzbget_port);
      return host ? (port ? `${host}:${port}` : host) : null;
    }
    case "qbittorrent":
      return text(values.qbittorrent_host) || null;
    case "deluge":
      return text(values.deluge_host) || null;
    case "transmission":
      return text(values.transmission_host) || null;
    case "ddl":
      return DDL_HOSTS;
    default:
      return null;
  }
}

/**
 * The usenet client a card stands for. When usenet is switched off
 * (NZB_DOWNLOADER 3) the card keeps the client whose server is still set, so
 * switching it back on needs no new choice.
 */
export function usenetClient(values: Values): ClientInfo | null {
  const code = Number(values.nzb_downloader ?? 3);
  const chosen = byCode("usenet", code);
  if (chosen) return chosen;
  if (text(values.sab_host)) return clientById("sabnzbd");
  if (text(values.nzbget_host)) return clientById("nzbget");
  return null;
}

export function torrentClient(values: Values): ClientInfo {
  return (
    byCode("torrent", Number(values.torrent_downloader ?? 0)) ??
    clientById("watchdir")
  );
}

export interface ClientCard {
  client: ClientInfo;
  enabled: boolean;
}

/** The cards in display order: usenet, torrent, then direct downloads. */
export function clientCards(
  values: Values,
  added: ReadonlySet<ClientKind> = new Set(),
): ClientCard[] {
  const cards: ClientCard[] = [];
  const usenet = usenetClient(values);
  if (usenet) {
    cards.push({
      client: usenet,
      enabled: Number(values.nzb_downloader ?? 3) !== 3,
    });
  }
  const torrent = torrentClient(values);
  const torrentsOn = Boolean(values.enable_torrents);
  if (torrentsOn || clientHost(torrent.id, values) || added.has("torrent")) {
    cards.push({ client: torrent, enabled: torrentsOn });
  }
  if (values.enable_ddl || added.has("ddl")) {
    cards.push({
      client: clientById("ddl"),
      enabled: Boolean(values.enable_ddl),
    });
  }
  return cards;
}

export interface RootRoute {
  root: string;
  category: string;
  savePath: string;
}

/** qBittorrent routes: one "library root | category | save path" per line. */
export function parseRootRoutes(value: string | null | undefined): RootRoute[] {
  return (value ?? "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [root = "", category = "", savePath = ""] = line
        .split("|")
        .map((part) => part.trim());
      return { root, category, savePath };
    });
}

export function formatRootRoutes(routes: RootRoute[]): string {
  return routes
    .filter((route) => route.root || route.category || route.savePath)
    .map((route) =>
      [route.root, route.category, route.savePath]
        .join(" | ")
        .replace(/\s\|\s$/, ""),
    )
    .join("\n");
}

/** The same scheme, host and port; what decides whether a password must be re-entered. */
export function hostKey(value: string | null | undefined): string | null {
  const raw = (value ?? "").trim();
  if (!raw) return null;
  try {
    const url = new URL(raw.includes("://") ? raw : `http://${raw}`);
    if (url.protocol !== "http:" && url.protocol !== "https:") return raw;
    const port = url.port || (url.protocol === "https:" ? "443" : "80");
    return `${url.protocol}//${url.hostname.toLowerCase()}:${port}`;
  } catch {
    return raw.toLowerCase();
  }
}
