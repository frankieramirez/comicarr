/**
 * Configuration type definitions
 */

/** Main configuration object (partial - add fields as needed) */
export interface Config {
  // Version
  version?: string;

  // General
  comic_dir?: string;
  log_dir?: string;
  data_dir?: string;

  // API
  api_key?: string;
  api_enabled?: boolean;

  // Download clients
  sab_host?: string;
  sab_apikey?: string;
  sab_category?: string;
  nzbget_host?: string;
  nzbget_username?: string;
  nzbget_password?: string;
  nzbget_category?: string;

  // Torrent clients
  rtorrent_host?: string;
  rtorrent_auth?: string;
  qbittorrent_host?: string;
  qbittorrent_username?: string;
  qbittorrent_password?: string;
  deluge_host?: string;
  deluge_password?: string;
  transmission_host?: string;
  transmission_username?: string;
  transmission_password?: string;

  // Content source toggles
  comicvine_enabled?: boolean;
  mangadex_enabled?: boolean;
  mangadex_languages?: string;
  mangadex_content_rating?: string;

  // Comic Vine
  comicvine_api?: string;

  // Search providers
  newznab?: NewznabProvider[];
  torznab?: TorznabProvider[];

  // UI preferences
  theme?: "light" | "dark" | "system";

  // Any additional config fields
  [key: string]: unknown;
}

/** Newznab provider configuration */
export interface NewznabProvider {
  name: string;
  host: string;
  apikey: string;
  enabled: boolean;
  categories?: string;
}

/** Torznab provider configuration */
export interface TorznabProvider {
  name: string;
  host: string;
  apikey: string;
  enabled: boolean;
  categories?: string;
}

/** Config update payload */
export type ConfigUpdate = Partial<Config>;
