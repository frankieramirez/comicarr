/**
 * Configuration type definitions
 */

import type { ReadableConfig } from "./config.generated";

/** Shape of `GET /api/config`: the registry-derived readable keys plus the
 *  handful of extras `get_safe_config` bolts on outside the registry. */
export interface Config extends ReadableConfig {
  version?: string;
  config_path?: string;
  data_dir?: string;
  python_version?: string;

  newznab?: ProviderConfigResponse["newznab"];
  torznab?: ProviderConfigResponse["newznab"];
}

/** Sanitized Newznab provider configuration returned by the settings API. */
export interface NewznabProvider {
  id?: number;
  name: string;
  host: string;
  verify: boolean;
  categories: string;
  enabled: boolean;
  api_key_set: boolean;
  api_key?: string;
  /**
   * The `i=` parameter of the indexer's RSS URL. Stored joined to the
   * categories as `uid#categories`, split apart by the API so the categories
   * field means categories. Newznab only — Torznab records have no uid.
   */
  rss_uid?: string;
}

export interface ProviderConfigResponse {
  newznab: {
    enabled: boolean;
    providers: NewznabProvider[];
  };
}

export type TorznabProvider = NewznabProvider;

/** Config update payload */
export type ConfigUpdate = Partial<Config>;
