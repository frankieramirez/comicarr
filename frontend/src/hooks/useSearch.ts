import {
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryResult,
  type UseMutationResult,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import type { SearchResult, PaginationMeta } from "@/types";

interface SearchResponse {
  results: SearchResult[];
  pagination: PaginationMeta;
}

interface RawSearchResult {
  comicimage?: string | null;
  comicthumb?: string | null;
  [key: string]: unknown;
}

type RawSearchResponse =
  | RawSearchResult[]
  | {
      results?: RawSearchResult[];
      pagination?: PaginationMeta;
    };

/**
 * Search for comics with server-side pagination
 */
export function useSearchComics(
  query: string,
  page = 1,
  sortBy: string | null = null,
  options: Partial<
    UseQueryOptions<RawSearchResponse, Error, SearchResponse>
  > = {},
): UseQueryResult<SearchResponse> {
  const limit = 20; // Results per page
  const offset = (page - 1) * limit;

  return useQuery({
    queryKey: ["search", query, page, sortBy],
    queryFn: () =>
      apiRequest<RawSearchResponse>("POST", "/api/search/comics", {
        name: query,
        limit,
        offset,
        ...(sortBy ? { sort: sortBy } : {}),
      }),
    // Transform backend field names to match frontend expectations
    select: (data: RawSearchResponse): SearchResponse => {
      // Handle old format (array) for backward compatibility
      if (Array.isArray(data)) {
        return {
          results: data.map((comic) => ({
            ...comic,
            image: comic.comicimage || comic.comicthumb || null,
          })) as SearchResult[],
          pagination: {
            total: data.length,
            limit,
            offset,
            returned: data.length,
          },
        };
      }
      // Handle new format (object with pagination)
      return {
        results: (data.results || []).map((comic) => ({
          ...comic,
          image: comic.comicimage || comic.comicthumb || null,
        })) as SearchResult[],
        pagination: data.pagination || { total: 0, limit, offset, returned: 0 },
      };
    },
    enabled: !!query && query.length > 2,
    staleTime: 10 * 60 * 1000,
    ...options,
  });
}

/**
 * Search for manga using MangaDex
 */
export function useSearchManga(
  query: string,
  page = 1,
  sortBy = "relevance",
  options: Partial<
    UseQueryOptions<RawSearchResponse, Error, SearchResponse>
  > = {},
): UseQueryResult<SearchResponse> {
  const limit = 20;
  const offset = (page - 1) * limit;

  return useQuery({
    queryKey: ["search", "manga", query, page, sortBy],
    queryFn: () =>
      apiRequest<RawSearchResponse>("POST", "/api/search/manga", {
        name: query,
        limit,
        offset,
        sort: sortBy,
      }),
    select: (data: RawSearchResponse): SearchResponse => {
      if (Array.isArray(data)) {
        return {
          results: data.map((manga) => ({
            ...manga,
            image: manga.comicimage || manga.comicthumb || null,
          })) as SearchResult[],
          pagination: {
            total: data.length,
            limit,
            offset,
            returned: data.length,
          },
        };
      }
      return {
        results: (data.results || []).map((manga) => ({
          ...manga,
          image: manga.comicimage || manga.comicthumb || null,
        })) as SearchResult[],
        pagination: data.pagination || { total: 0, limit, offset, returned: 0 },
      };
    },
    enabled: !!query && query.length > 2,
    staleTime: 10 * 60 * 1000,
    ...options,
  });
}

/**
 * Add a comic to the library
 */
export function useAddComic(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId: string) =>
      apiRequest("POST", "/api/search/add", { id: comicId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });
}

/**
 * Add a manga to the library
 */
export function useAddManga(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (mangaId: string) =>
      apiRequest("POST", "/api/search/add-manga", { id: mangaId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });
}
