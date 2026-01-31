import { useMemo } from "react";
import { useSearchComics, useSearchManga } from "./useSearch";
import type { SearchResult, PaginationMeta, ContentType } from "@/types";

export interface UnifiedSearchResult extends SearchResult {
  content_type: ContentType;
}

export interface UnifiedSearchResponse {
  results: UnifiedSearchResult[];
  pagination: PaginationMeta;
  comicPagination?: PaginationMeta;
  mangaPagination?: PaginationMeta;
}

/**
 * Unified search hook that combines comic and manga search results
 * Fetches from both APIs in parallel and merges results
 */
export function useUnifiedSearch(
  query: string,
  page = 1,
  comicSort = "start_year:desc",
  mangaSort = "relevance",
) {
  // Fetch both comics and manga in parallel
  const comicSearch = useSearchComics(query, page, comicSort);
  const mangaSearch = useSearchManga(query, page, mangaSort);

  // Combine loading states
  const isLoading = comicSearch.isLoading || mangaSearch.isLoading;

  // Combine errors (prioritize comic error if both fail)
  const error = comicSearch.error || mangaSearch.error;

  // Merge and interleave results
  const data = useMemo<UnifiedSearchResponse | undefined>(() => {
    // If both are still loading, return undefined
    if (!comicSearch.data && !mangaSearch.data) {
      return undefined;
    }

    const comicResults = comicSearch.data?.results || [];
    const mangaResults = mangaSearch.data?.results || [];

    // Tag results with content type
    const taggedComics: UnifiedSearchResult[] = comicResults.map((r) => ({
      ...r,
      content_type: "comic" as ContentType,
    }));

    const taggedManga: UnifiedSearchResult[] = mangaResults.map((r) => ({
      ...r,
      content_type: "manga" as ContentType,
    }));

    // Interleave results (comic, manga, comic, manga...)
    const merged: UnifiedSearchResult[] = [];
    const maxLength = Math.max(taggedComics.length, taggedManga.length);

    for (let i = 0; i < maxLength; i++) {
      if (i < taggedComics.length) {
        merged.push(taggedComics[i]);
      }
      if (i < taggedManga.length) {
        merged.push(taggedManga[i]);
      }
    }

    // Calculate combined pagination
    const comicTotal = comicSearch.data?.pagination?.total || 0;
    const mangaTotal = mangaSearch.data?.pagination?.total || 0;
    const limit = comicSearch.data?.pagination?.limit || 50;

    return {
      results: merged,
      pagination: {
        total: comicTotal + mangaTotal,
        limit: limit * 2, // Combined limit from both sources
        offset: (page - 1) * limit,
        returned: merged.length,
      },
      comicPagination: comicSearch.data?.pagination,
      mangaPagination: mangaSearch.data?.pagination,
    };
  }, [comicSearch.data, mangaSearch.data, page]);

  return {
    data,
    isLoading,
    error,
    comicSearch,
    mangaSearch,
  };
}
