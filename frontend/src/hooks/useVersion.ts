import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import type { VersionInfo } from "@/lib/updateStatus";

export const VERSION_QUERY_KEY = ["system", "version"] as const;

/** Poll cadence for update availability (#473 / #460). */
export const VERSION_POLL_MS = 10 * 60 * 1000;

/**
 * Live version / update state.
 *
 * Shared by Settings → About and the sidebar chip. Polls every 10 minutes and
 * refetches on mount and window focus. No SSE path for update availability.
 */
export function useVersionInfo(options?: {
  enabled?: boolean;
}): UseQueryResult<VersionInfo> {
  const enabled = options?.enabled ?? true;
  return useQuery({
    queryKey: VERSION_QUERY_KEY,
    queryFn: () => apiRequest<VersionInfo>("GET", "/api/system/version"),
    enabled,
    refetchInterval: enabled ? VERSION_POLL_MS : false,
    refetchOnWindowFocus: true,
    refetchOnMount: true,
    staleTime: 0,
    retry: false,
  });
}

export function useForceVersionCheck(): UseMutationResult<
  VersionInfo,
  Error,
  void
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () =>
      apiRequest<VersionInfo>("POST", "/api/system/version/check"),
    onSuccess: (data) => {
      queryClient.setQueryData(VERSION_QUERY_KEY, data);
    },
  });
}

/** True only when the last successful poll says behind. */
export function isUpdateBehind(
  status: "pending" | "error" | "success",
  data: VersionInfo | undefined,
): boolean {
  if (status !== "success" || !data) return false;
  return data.update_state === "behind" && Boolean(data.latest_version);
}
