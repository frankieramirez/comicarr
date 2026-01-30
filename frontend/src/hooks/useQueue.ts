import { useQuery, useMutation, useQueryClient, type UseQueryResult, type UseMutationResult } from '@tanstack/react-query';
import { apiCall } from '@/lib/api';
import type { WantedIssue, UpcomingIssue, PaginationMeta } from '@/types';

interface WantedResponse {
  issues: WantedIssue[];
  pagination: PaginationMeta;
}

// Query Hooks
export function useUpcoming(includeDownloaded = false): UseQueryResult<UpcomingIssue[]> {
  return useQuery({
    queryKey: ['upcoming', includeDownloaded],
    queryFn: () => apiCall<UpcomingIssue[]>('getUpcoming', includeDownloaded ? { include_downloaded_issues: 'Y' } : {}),
    staleTime: 2 * 60 * 1000, // 2 minutes (more frequent than series)
  });
}

export function useWanted(limit = 50, offset = 0): UseQueryResult<WantedResponse> {
  return useQuery({
    queryKey: ['wanted', limit, offset],
    queryFn: () => apiCall<WantedResponse>('getWanted', { limit, offset }),
    staleTime: 2 * 60 * 1000,
  });
}

// Mutation Hooks
export function useForceSearch(): UseMutationResult<unknown, Error, void> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiCall('forceSearch'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wanted'] });
      queryClient.invalidateQueries({ queryKey: ['upcoming'] });
    },
  });
}

export function useBulkQueueIssues(): UseMutationResult<void, Error, string[]> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (issueIds: string[]) => {
      // Process sequentially to avoid rate limiting
      for (const id of issueIds) {
        await apiCall('queueIssue', { id });
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wanted'] });
      queryClient.invalidateQueries({ queryKey: ['upcoming'] });
      queryClient.invalidateQueries({ queryKey: ['series'] });
    },
  });
}

export function useBulkUnqueueIssues(): UseMutationResult<void, Error, string[]> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (issueIds: string[]) => {
      // Process sequentially to avoid rate limiting
      for (const id of issueIds) {
        await apiCall('unqueueIssue', { id });
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wanted'] });
      queryClient.invalidateQueries({ queryKey: ['upcoming'] });
      queryClient.invalidateQueries({ queryKey: ['series'] });
    },
  });
}
