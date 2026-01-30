import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiCall } from '@/lib/api';

/**
 * Search for comics with server-side pagination
 * @param {string} query - Search query
 * @param {number} page - Page number (1-indexed)
 * @param {string} sortBy - Sort field and direction (e.g., 'start_year:desc')
 * @param {object} options - Additional react-query options
 */
export function useSearchComics(query, page = 1, sortBy = 'start_year:desc', options = {}) {
  const limit = 50;  // Results per page
  const offset = (page - 1) * limit;

  return useQuery({
    queryKey: ['search', query, page, sortBy],  // Include page and sort in cache key
    queryFn: () => apiCall('findComic', {
      name: query,
      limit: limit.toString(),
      offset: offset.toString(),
      sort: sortBy
    }),
    // Transform backend field names to match frontend expectations
    // Backend can return either:
    // - Old format: array of comics
    // - New format: {results: [...], pagination: {...}}
    select: (data) => {
      // Handle old format (array) for backward compatibility
      if (Array.isArray(data)) {
        return {
          results: data.map(comic => ({
            ...comic,
            image: comic.comicimage || comic.comicthumb || null,
          })),
          pagination: {
            total: data.length,
            limit,
            offset,
            returned: data.length
          }
        };
      }
      // Handle new format (object with pagination)
      return {
        results: (data.results || []).map(comic => ({
          ...comic,
          image: comic.comicimage || comic.comicthumb || null,
        })),
        pagination: data.pagination
      };
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
