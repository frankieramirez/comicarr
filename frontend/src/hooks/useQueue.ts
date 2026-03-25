import {
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryResult,
  type UseMutationResult,
} from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import type { WantedIssue, UpcomingIssue, PaginationMeta } from "@/types";

interface WantedResponse {
  issues: WantedIssue[];
  pagination: PaginationMeta;
}

// Query Hooks
export function useUpcoming(
  includeDownloaded = false,
): UseQueryResult<UpcomingIssue[]> {
  return useQuery({
    queryKey: ["upcoming", includeDownloaded],
    queryFn: () =>
      apiRequest<UpcomingIssue[]>(
        "GET",
        `/api/upcoming${includeDownloaded ? "?include_downloaded_issues=true" : ""}`,
      ),
    staleTime: 2 * 60 * 1000, // 2 minutes (more frequent than series)
  });
}

export function useWanted(
  limit = 50,
  offset = 0,
): UseQueryResult<WantedResponse> {
  return useQuery({
    queryKey: ["wanted", limit, offset],
    queryFn: () =>
      apiRequest<WantedResponse>(
        "GET",
        `/api/wanted?limit=${limit}&offset=${offset}`,
      ),
    staleTime: 2 * 60 * 1000,
  });
}

// Mutation Hooks
export function useForceSearch(): UseMutationResult<unknown, Error, void> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest("POST", "/api/search/force"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wanted"] });
      queryClient.invalidateQueries({ queryKey: ["upcoming"] });
    },
  });
}

export function useBulkQueueIssues(): UseMutationResult<void, Error, string[]> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (issueIds: string[]) => {
      // Process sequentially to avoid rate limiting
      for (const id of issueIds) {
        await apiRequest("PUT", `/api/series/issues/${id}/queue`);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wanted"] });
      queryClient.invalidateQueries({ queryKey: ["upcoming"] });
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });
}

export function useBulkUnqueueIssues(): UseMutationResult<
  void,
  Error,
  string[]
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (issueIds: string[]) => {
      // Process sequentially to avoid rate limiting
      for (const id of issueIds) {
        await apiRequest("PUT", `/api/series/issues/${id}/unqueue`);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wanted"] });
      queryClient.invalidateQueries({ queryKey: ["upcoming"] });
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });
}
