import type { AcquisitionHealthResponse } from "@/hooks/useAcquisitionHealth";

/**
 * `GET /api/search/health` on an install with no indexer and no download
 * client, trimmed from a real v0.56 server running a 400-series library.
 */
export const UNCONFIGURED_SEARCH_HEALTH: AcquisitionHealthResponse = {
  providers: [],
  routes: {
    ddl: {
      configured: false,
      enabled: false,
      downstream: "local",
      client_ready: true,
      path_ready: true,
      downstream_ready: true,
      ready: false,
      reason: "disabled",
      configured_provider_count: 0,
      providers: [],
    },
    nzb: {
      configured: false,
      enabled: false,
      downstream: "disabled",
      client_ready: false,
      path_ready: false,
      downstream_ready: false,
      ready: false,
      reason: "downloader_disabled",
      configured_provider_count: 0,
      providers: [],
    },
    torrent: {
      configured: false,
      enabled: false,
      downstream: "watchfolder",
      client_ready: true,
      path_ready: false,
      downstream_ready: false,
      ready: false,
      reason: "disabled",
      configured_provider_count: 0,
      providers: [],
    },
  },
  viable_route: false,
  workers: {
    search: { state: "idle", alive: true, live: true, healthy: true },
  },
  maintenance: { blocked: false },
  blocked_producer_count: 0,
};
