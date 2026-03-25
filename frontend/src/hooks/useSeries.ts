import {
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryResult,
  type UseMutationResult,
} from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import type { Comic, SeriesDetail } from "@/types";

/**
 * Fetch all series from the library
 */
export function useSeries(): UseQueryResult<Comic[]> {
  return useQuery({
    queryKey: ["series"],
    queryFn: () => apiRequest<Comic[]>("GET", "/api/series"),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Fetch a single series with its issues
 */
export function useSeriesDetail(
  comicId: string | undefined,
): UseQueryResult<SeriesDetail> {
  return useQuery({
    queryKey: ["series", comicId],
    queryFn: () => apiRequest<SeriesDetail>("GET", `/api/series/${comicId}`),
    enabled: !!comicId,
  });
}

/**
 * Pause a series
 */
export function usePauseSeries(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId: string) =>
      apiRequest("PUT", `/api/series/${comicId}/pause`),
    onSuccess: (_, comicId) => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
      queryClient.invalidateQueries({ queryKey: ["series", comicId] });
    },
  });
}

/**
 * Resume a series
 */
export function useResumeSeries(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId: string) =>
      apiRequest("PUT", `/api/series/${comicId}/resume`),
    onSuccess: (_, comicId) => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
      queryClient.invalidateQueries({ queryKey: ["series", comicId] });
    },
  });
}

/**
 * Refresh series metadata
 */
export function useRefreshSeries(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId: string) =>
      apiRequest("POST", `/api/series/${comicId}/refresh`),
    onSuccess: (_, comicId) => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
      queryClient.invalidateQueries({ queryKey: ["series", comicId] });
    },
  });
}

/**
 * Delete a series
 */
export function useDeleteSeries(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId: string) =>
      apiRequest("DELETE", `/api/series/${comicId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });
}

/**
 * Queue an issue (mark as wanted)
 */
export function useQueueIssue(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (issueId: string) =>
      apiRequest("PUT", `/api/series/issues/${issueId}/queue`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
      queryClient.invalidateQueries({ queryKey: ["wanted"] });
    },
  });
}

/**
 * Unqueue an issue (mark as skipped)
 */
export function useUnqueueIssue(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (issueId: string) =>
      apiRequest("PUT", `/api/series/issues/${issueId}/unqueue`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
      queryClient.invalidateQueries({ queryKey: ["wanted"] });
    },
  });
}
