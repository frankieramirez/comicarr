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

  // Search providers
  newznab?: NewznabProvider[];
  torznab?: TorznabProvider[];
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
