import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiCall } from '@/lib/api';

// Query Hooks
export function useUpcoming(includeDownloaded = false) {
  return useQuery({
    queryKey: ['upcoming', includeDownloaded],
    queryFn: () => apiCall('getUpcoming', includeDownloaded ? { include_downloaded_issues: 'Y' } : {}),
    staleTime: 2 * 60 * 1000, // 2 minutes (more frequent than series)
  });
}

export function useWanted(limit = 50, offset = 0) {
  return useQuery({
    queryKey: ['wanted', limit, offset],
    queryFn: () => apiCall('getWanted', { limit, offset }),
    staleTime: 2 * 60 * 1000,
  });
}

// Mutation Hooks
export function useForceSearch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiCall('forceSearch'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wanted'] });
      queryClient.invalidateQueries({ queryKey: ['upcoming'] });
    },
  });
}

export function useBulkQueueIssues() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (issueIds) => {
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

export function useBulkUnqueueIssues() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (issueIds) => {
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
