import { useQuery, useMutation, useQueryClient, type UseQueryResult, type UseMutationResult } from '@tanstack/react-query';
import { apiCall } from '@/lib/api';
import type { Comic, SeriesDetail } from '@/types';

/**
 * Fetch all series from the library
 */
export function useSeries(): UseQueryResult<Comic[]> {
  return useQuery({
    queryKey: ['series'],
    queryFn: () => apiCall<Comic[]>('getIndex'),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Fetch a single series with its issues
 */
export function useSeriesDetail(comicId: string | undefined): UseQueryResult<SeriesDetail> {
  return useQuery({
    queryKey: ['series', comicId],
    queryFn: () => apiCall<SeriesDetail>('getComic', { id: comicId }),
    enabled: !!comicId,
  });
}

/**
 * Pause a series
 */
export function usePauseSeries(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId: string) => apiCall('pauseComic', { id: comicId }),
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
export function useResumeSeries(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId: string) => apiCall('resumeComic', { id: comicId }),
    onSuccess: (_, comicId) => {
      queryClient.invalidateQueries({ queryKey: ['series'] });
      queryClient.invalidateQueries({ queryKey: ['series', comicId] });
    },
  });
}

/**
 * Refresh series metadata
 */
export function useRefreshSeries(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId: string) => apiCall('refreshComic', { id: comicId }),
    onSuccess: (_, comicId) => {
      queryClient.invalidateQueries({ queryKey: ['series'] });
      queryClient.invalidateQueries({ queryKey: ['series', comicId] });
    },
  });
}

/**
 * Delete a series
 */
export function useDeleteSeries(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId: string) => apiCall('delComic', { id: comicId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['series'] });
    },
  });
}

/**
 * Queue an issue (mark as wanted)
 */
export function useQueueIssue(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (issueId: string) => apiCall('queueIssue', { id: issueId }),
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
export function useUnqueueIssue(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (issueId: string) => apiCall('unqueueIssue', { id: issueId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['series'] });
      queryClient.invalidateQueries({ queryKey: ['wanted'] });
    },
  });
}
