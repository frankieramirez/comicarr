import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import { ACTIVITY_STATUS_QUERY_KEY } from "@/lib/activityKeys";

const STATUS_POLL_MS = 30 * 1000;

/** Derived open-work counts from GET /api/activity/status (never narrative). */
export interface ActivityStatusResponse {
  in_flight: number;
  /**
   * Subset of in_flight that has already survived a restart — a qualifier on
   * in_flight, never added to it. Lets a surface say "N in flight (K recovered
   * from a restart)" instead of one opaque number (#555).
   */
  recovery_pending?: number;
  attention: number;
}

/**
 * Quiet-count inputs for the global status indicator.
 * Polls every 30s; shared SSE invalidates this key via useServerEvents.
 */
export function useActivityStatus() {
  return useQuery<ActivityStatusResponse>({
    queryKey: ACTIVITY_STATUS_QUERY_KEY,
    queryFn: () =>
      apiRequest<ActivityStatusResponse>("GET", "/api/activity/status"),
    staleTime: 15 * 1000,
    refetchInterval: STATUS_POLL_MS,
  });
}
