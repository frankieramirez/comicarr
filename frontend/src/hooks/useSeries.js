import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiCall } from '@/lib/api';

/**
 * Fetch all series from the library
 */
export function useSeries() {
  return useQuery({
    queryKey: ['series'],
    queryFn: () => apiCall('getIndex'),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Fetch a single series with its issues
 */
export function useSeriesDetail(comicId) {
  return useQuery({
    queryKey: ['series', comicId],
    queryFn: () => apiCall('getComic', { id: comicId }),
    enabled: !!comicId,
  });
}

/**
 * Pause a series
 */
export function usePauseSeries() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId) => apiCall('pauseComic', { id: comicId }),
    onSuccess: (_, comicId) => {
      // Invalidate both the series list and the specific series detail
      queryClient.invalidateQueries({ queryKey: ['series'] });
      queryClient.invalidateQueries({ queryKey: ['series', comicId] });
    },
  });
}

/**
 * Resume a series
 */
export function useResumeSeries() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId) => apiCall('resumeComic', { id: comicId }),
    onSuccess: (_, comicId) => {
      queryClient.invalidateQueries({ queryKey: ['series'] });
      queryClient.invalidateQueries({ queryKey: ['series', comicId] });
    },
  });
}

/**
 * Refresh series metadata
 */
export function useRefreshSeries() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId) => apiCall('refreshComic', { id: comicId }),
    onSuccess: (_, comicId) => {
      queryClient.invalidateQueries({ queryKey: ['series'] });
      queryClient.invalidateQueries({ queryKey: ['series', comicId] });
    },
  });
}

/**
 * Delete a series
 */
export function useDeleteSeries() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId) => apiCall('delComic', { id: comicId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['series'] });
    },
  });
}

/**
 * Queue an issue (mark as wanted)
 */
export function useQueueIssue() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (issueId) => apiCall('queueIssue', { id: issueId }),
    onSuccess: () => {
      // Invalidate all series-related queries
      queryClient.invalidateQueries({ queryKey: ['series'] });
      queryClient.invalidateQueries({ queryKey: ['wanted'] });
    },
  });
}

/**
 * Unqueue an issue (mark as skipped)
 */
export function useUnqueueIssue() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (issueId) => apiCall('unqueueIssue', { id: issueId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['series'] });
      queryClient.invalidateQueries({ queryKey: ['wanted'] });
    },
  });
}
