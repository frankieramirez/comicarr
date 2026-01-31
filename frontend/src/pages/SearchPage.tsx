import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Search as SearchIcon, ChevronLeft, ChevronRight, BookOpen, Book, Library } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useSearchComics, useSearchManga } from "@/hooks/useSearch";
import { useUnifiedSearch } from "@/hooks/useUnifiedSearch";
import SearchResultsTable from "@/components/search/SearchResultsTable";
import { Skeleton } from "@/components/ui/skeleton";
import type { ContentType } from "@/types/entities";

type SearchMode = "all" | ContentType;

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  // Get parameters from URL
  const urlQuery = searchParams.get("q") || "";
  const urlPage = parseInt(searchParams.get("page") || "1") || 1;
  const urlSort = searchParams.get("sort") || "year_desc";
  const urlSearchMode = (searchParams.get("type") as SearchMode) || "all";

  // Initialize search query from URL parameter
  const [searchQuery, setSearchQuery] = useState(urlQuery);
  const [searchMode, setSearchMode] = useState<SearchMode>(urlSearchMode);

  // Map frontend sort values to ComicVine API format (for comics)
  const comicSortMapping: Record<string, string> = {
    year_desc: "start_year:desc",
    year_asc: "start_year:asc",
    issues_desc: "count_of_issues:desc",
    issues_asc: "count_of_issues:asc",
    name_asc: "name:asc",
    name_desc: "name:desc",
  };

  // Map frontend sort values to MangaDex API format (for manga)
  const mangaSortMapping: Record<string, string> = {
    year_desc: "year_desc",
    year_asc: "year_asc",
    name_asc: "title_asc",
    name_desc: "title_desc",
    relevance: "relevance",
    latest: "latest",
    follows: "follows",
  };

  const comicApiSort = comicSortMapping[urlSort] || urlSort;
  const mangaApiSort = mangaSortMapping[urlSort] || "relevance";

  // Use unified search for "all" mode
  const unifiedSearch = useUnifiedSearch(
    searchMode === "all" ? urlQuery : "",
    urlPage,
    comicApiSort,
    mangaApiSort,
  );

  // Use comic search for comic-only mode
  const comicSearch = useSearchComics(
    searchMode === "comic" ? urlQuery : "",
    urlPage,
    comicApiSort,
  );

  // Use manga search for manga-only mode
  const mangaSearch = useSearchManga(
    searchMode === "manga" ? urlQuery : "",
    urlPage,
    mangaApiSort,
  );

  // Select the active search based on search mode
  const activeSearch = searchMode === "all"
    ? unifiedSearch
    : searchMode === "manga"
      ? mangaSearch
      : comicSearch;

  const { data, isLoading, error } = activeSearch;
  const searchResults = data?.results || [];
  const pagination = data?.pagination;

  const handleSearch = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (searchQuery.trim().length > 2) {
      setSearchParams({ q: searchQuery.trim(), page: "1", sort: urlSort, type: searchMode });
    }
  };

  const handleSearchModeChange = (newMode: SearchMode) => {
    setSearchMode(newMode);
    // If there's a query, re-search with new mode
    if (urlQuery) {
      const newSort = newMode === "manga" ? "relevance" : urlSort;
      setSearchParams({ q: urlQuery, page: "1", sort: newSort, type: newMode });
    }
  };

  const handlePageChange = (newPage: number) => {
    const params: Record<string, string> = Object.fromEntries(searchParams);
    params.page = newPage.toString();
    setSearchParams(params);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleSortChange = (value: string) => {
    const params: Record<string, string> = Object.fromEntries(searchParams);
    params.sort = value;
    params.page = "1"; // Reset to page 1 when sort changes
    setSearchParams(params);
  };

  // Calculate pagination info from server metadata
  const totalPages = pagination
    ? Math.ceil(pagination.total / pagination.limit)
    : 0;
  const startIndex = pagination ? pagination.offset + 1 : 0;
  const endIndex = pagination
    ? pagination.offset + (pagination.returned ?? 0)
    : 0;

  // Get title based on search mode
  const getTitle = () => {
    switch (searchMode) {
      case "all":
        return "Search All";
      case "manga":
        return "Search Manga";
      default:
        return "Search Comics";
    }
  };

  return (
    <div className="space-y-4 page-transition">
      {/* Page Title */}
      <h1 className="text-3xl font-bold">{getTitle()}</h1>

      {/* Content Type Toggle */}
      <div className="flex gap-2">
        <Button
          variant={searchMode === "all" ? "default" : "outline"}
          onClick={() => handleSearchModeChange("all")}
          className="flex items-center"
        >
          <Library className="w-4 h-4 mr-2" />
          All
        </Button>
        <Button
          variant={searchMode === "comic" ? "default" : "outline"}
          onClick={() => handleSearchModeChange("comic")}
          className="flex items-center"
        >
          <Book className="w-4 h-4 mr-2" />
          Comics
        </Button>
        <Button
          variant={searchMode === "manga" ? "default" : "outline"}
          onClick={() => handleSearchModeChange("manga")}
          className="flex items-center"
        >
          <BookOpen className="w-4 h-4 mr-2" />
          Manga
        </Button>
      </div>

      {/* Search Form */}
      <form onSubmit={handleSearch} className="flex gap-2 max-w-2xl">
        <Input
          type="text"
          placeholder={`Enter ${searchMode === "all" ? "comic or manga" : searchMode} name...`}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="flex-1"
        />
        <Button
          type="submit"
          disabled={searchQuery.trim().length < 3}
          className="flex items-center"
        >
          <SearchIcon className="w-4 h-4 mr-2" />
          Search
        </Button>
      </form>

      {/* Results count */}
      {urlQuery && (pagination || isLoading) && (
        <p className="text-muted-foreground">
          {isLoading ? (
            "Searching..."
          ) : (
            <>
              Showing {startIndex}-{endIndex} of {pagination?.total || 0}{" "}
              results for "{urlQuery}"
              {searchMode === "all" && unifiedSearch.data && (
                <span className="text-xs ml-2">
                  ({unifiedSearch.comicSearch.data?.pagination?.total || 0} comics, {unifiedSearch.mangaSearch.data?.pagination?.total || 0} manga)
                </span>
              )}
            </>
          )}
        </p>
      )}

      {/* Loading State */}
      {isLoading && (
        <div className="rounded-lg border border-card-border bg-card card-shadow overflow-hidden">
          <div className="bg-muted/50 px-6 py-3 border-b border-card-border">
            <Skeleton className="h-4 w-full max-w-md" />
          </div>
          {[...Array(10)].map((_, i) => (
            <div
              key={i}
              className="px-6 py-4 border-b border-card-border last:border-0"
            >
              <Skeleton className="h-6 w-full" />
            </div>
          ))}
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="text-center py-12">
          <p className="text-red-600 text-lg">Search failed</p>
          <p className="text-muted-foreground text-sm mt-2">{error.message}</p>
        </div>
      )}

      {/* No Results State */}
      {!isLoading && !error && urlQuery && searchResults.length === 0 && (
        <div className="text-center py-12">
          <p className="text-muted-foreground text-lg">
            No results found for "{urlQuery}"
          </p>
          <p className="text-gray-400 text-sm mt-2">
            Try a different search term or check your spelling.
          </p>
        </div>
      )}

      {/* Results Table */}
      {!isLoading && !error && searchResults.length > 0 && (
        <div>
          <SearchResultsTable
            results={searchResults}
            currentSort={urlSort}
            onSortChange={handleSortChange}
            contentType={searchMode === "all" ? undefined : searchMode}
            showTypeColumn={searchMode === "all"}
          />

          {/* Pagination Controls */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-6 pt-4 border-t border-card-border">
              <Button
                variant="outline"
                onClick={() => handlePageChange(urlPage - 1)}
                disabled={urlPage === 1}
              >
                <ChevronLeft className="w-4 h-4 mr-2" />
                Previous
              </Button>

              <span className="text-sm text-muted-foreground">
                Page {urlPage} of {totalPages}
              </span>

              <Button
                variant="outline"
                onClick={() => handlePageChange(urlPage + 1)}
                disabled={urlPage >= totalPages}
              >
                Next
                <ChevronRight className="w-4 h-4 ml-2" />
              </Button>
            </div>
          )}
        </div>
      )}

      {/* Empty State - No Search Yet */}
      {!urlQuery && (
        <div className="text-center py-12">
          <SearchIcon className="w-16 h-16 text-gray-300 mx-auto mb-4" />
          <p className="text-muted-foreground text-lg">
            Enter a search term to find {searchMode === "all" ? "comics and manga" : searchMode === "manga" ? "manga" : "comics"}
          </p>
          <p className="text-gray-400 text-sm mt-2">
            Search requires at least 3 characters
          </p>
        </div>
      )}
    </div>
  );
}
