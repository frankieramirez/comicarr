import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiCall } from '@/lib/api';

/**
 * Search for comics
 */
export function useSearchComics(query, options = {}) {
  return useQuery({
    queryKey: ['search', query],
    queryFn: () => apiCall('findComic', { name: query }),
    // Transform backend field names to match frontend expectations
    // Backend returns: comicimage, comicthumb
    // Frontend expects: image
    select: (data) => {
      if (!Array.isArray(data)) return data;
      return data.map(comic => ({
        ...comic,
        image: comic.comicimage || comic.comicthumb || null,
      }));
    },
    enabled: !!query && query.length > 2, // Only search if query is more than 2 chars
    staleTime: 10 * 60 * 1000, // 10 minutes - search results don't change often
    ...options,
  });
}

/**
 * Add a comic to the library
 */
export function useAddComic() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId) => apiCall('addComic', { id: comicId }),
    onSuccess: () => {
      // Invalidate series list to show the newly added comic
      queryClient.invalidateQueries({ queryKey: ['series'] });
    },
  });
}
