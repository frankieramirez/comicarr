/**
 * Configuration type definitions
 */

import type { ReadableConfig } from "./config.generated";

export type SearchProviderKind = "newznab" | "torznab";

/** Shared Search-provider fields returned by the settings API. */
interface SearchProviderFields {
  id?: number;
  name: string;
  host: string;
  verify: boolean;
  categories: string;
  enabled: boolean;
  api_key_set: boolean;
  api_key?: string;
}

/** Sanitized Newznab provider configuration returned by the settings API. */
export interface NewznabProvider extends SearchProviderFields {
  /**
   * The `i=` parameter of the indexer's RSS URL. Stored joined to the
   * categories as `uid#categories`, split apart by the API so the categories
   * field means categories. Newznab only — Torznab records have no uid.
   */
  rss_uid?: string;
}

/** Sanitized Torznab provider configuration. No `rss_uid` — enforced by
 *  `SearchProvider` on the server. */
export type TorznabProvider = SearchProviderFields;

export interface SearchProviderGroup<T extends SearchProviderFields> {
  enabled: boolean;
  providers: T[];
}

export interface ProviderConfigResponse {
  newznab: SearchProviderGroup<NewznabProvider>;
  torznab: SearchProviderGroup<TorznabProvider>;
}

/** Shape of `GET /api/config`: the registry-derived readable keys plus the
 *  handful of extras `get_safe_config` bolts on outside the registry. */
export interface Config extends ReadableConfig {
  version?: string;
  config_path?: string;
  data_dir?: string;
  python_version?: string;

  newznab?: ProviderConfigResponse["newznab"];
  torznab?: ProviderConfigResponse["torznab"];
}

/** Config update payload */
export type ConfigUpdate = Partial<Config>;
