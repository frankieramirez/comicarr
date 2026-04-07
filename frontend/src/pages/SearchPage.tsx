import { useState, useCallback } from "react";
import { useSearchParams, Link } from "react-router-dom";
import {
  Search as SearchIcon,
  ChevronLeft,
  ChevronRight,
  BookOpen,
  Book,
  ArrowUpDown,
  Settings,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useSearchComics, useSearchManga } from "@/hooks/useSearch";
import { useContentSources } from "@/hooks/useContentSources";
import SearchResultsTable from "@/components/search/SearchResultsTable";
import { Skeleton } from "@/components/ui/skeleton";
import type { ContentType } from "@/types/entities";

// Sort option definition
interface SortOption {
  value: string;
  label: string;
}

const COMIC_SORT_OPTIONS: SortOption[] = [
  { value: "relevance", label: "Relevance" },
  { value: "year_desc", label: "Year (Newest)" },
  { value: "year_asc", label: "Year (Oldest)" },
  { value: "name_asc", label: "Name (A-Z)" },
  { value: "name_desc", label: "Name (Z-A)" },
  { value: "issues_desc", label: "Most Issues" },
  { value: "issues_asc", label: "Fewest Issues" },
];

const MANGA_SORT_OPTIONS: SortOption[] = [
  { value: "relevance", label: "Relevance" },
  { value: "year_desc", label: "Year (Newest)" },
  { value: "year_asc", label: "Year (Oldest)" },
  { value: "name_asc", label: "Name (A-Z)" },
  { value: "name_desc", label: "Name (Z-A)" },
  { value: "follows", label: "Most Followed" },
  { value: "latest", label: "Latest Upload" },
];

const SORT_OPTIONS: Record<ContentType, SortOption[]> = {
  comic: COMIC_SORT_OPTIONS,
  manga: MANGA_SORT_OPTIONS,
};

// Map frontend sort values to ComicVine API format
const comicSortMapping: Record<string, string | null> = {
  relevance: null,
  year_desc: "start_year:desc",
  year_asc: "start_year:asc",
  issues_desc: "count_of_issues:desc",
  issues_asc: "count_of_issues:asc",
  name_asc: "name:asc",
  name_desc: "name:desc",
};

// Map frontend sort values to MangaDex API format
const mangaSortMapping: Record<string, string> = {
  relevance: "relevance",
  year_desc: "year_desc",
  year_asc: "year_asc",
  name_asc: "title_asc",
  name_desc: "title_desc",
  follows: "follows",
  latest: "latest",
};

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { comicsEnabled, comicsConfigured, mangaEnabled } = useContentSources();

  // Get parameters from URL
  const urlQuery = searchParams.get("q") || "";
  const urlPage = parseInt(searchParams.get("page") || "1") || 1;
  const urlSort = searchParams.get("sort") || "relevance";

  // Derive search mode from URL, falling back based on what's enabled
  const urlType = searchParams.get("type") as ContentType | null;
  const searchMode: ContentType = urlType
    ? urlType === "manga" && !mangaEnabled
      ? "comic"
      : urlType === "comic" && !comicsEnabled
        ? "manga"
        : urlType
    : comicsEnabled
      ? "comic"
      : "manga";

  const [searchQuery, setSearchQuery] = useState(urlQuery);
  const [columnToggleEl, setColumnToggleEl] = useState<HTMLDivElement | null>(
    null,
  );
  const columnToggleCallback = useCallback(
    (node: HTMLDivElement | null) => setColumnToggleEl(node),
    [],
  );

  // Map sort to API format based on mode
  const comicApiSort = comicSortMapping[urlSort] ?? urlSort;
  const mangaApiSort = mangaSortMapping[urlSort] || "relevance";

  // Use comic search for comic mode
  const comicSearch = useSearchComics(
    searchMode === "comic" ? urlQuery : "",
    urlPage,
    comicApiSort,
  );

  // Use manga search for manga mode
  const mangaSearch = useSearchManga(
    searchMode === "manga" ? urlQuery : "",
    urlPage,
    mangaApiSort,
  );

  // Select the active search based on search mode
  const activeSearch = searchMode === "manga" ? mangaSearch : comicSearch;

  const { data, isLoading, error } = activeSearch;
  const searchResults = data?.results || [];
  const pagination = data?.pagination;

  // Get sort options for current mode
  const sortOptions = SORT_OPTIONS[searchMode];

  const handleSearch = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (searchQuery.trim().length > 2) {
      setSearchParams({
        q: searchQuery.trim(),
        page: "1",
        sort: urlSort,
        type: searchMode,
      });
    }
  };

  const handleSearchModeChange = (newMode: ContentType) => {
    // Validate sort against new mode's options
    const validSorts = SORT_OPTIONS[newMode].map((o) => o.value);
    const newSort = validSorts.includes(urlSort) ? urlSort : "relevance";
    const params: Record<string, string> = {
      type: newMode,
      sort: newSort,
      page: "1",
    };
    if (urlQuery) params.q = urlQuery;
    setSearchParams(params);
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
    params.page = "1";
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

  return (
    <div className="space-y-4 page-transition min-w-0 overflow-hidden">
      {/* Page Title */}
      <h1 className="text-3xl font-bold">
        {searchMode === "manga" ? "Search Manga" : "Search Comics"}
      </h1>

      {/* Content Type Toggle - only show when both sources are enabled */}
      {comicsEnabled && mangaEnabled && (
        <div className="flex gap-2">
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
      )}

      {/* Search Form */}
      <form onSubmit={handleSearch} className="flex gap-2 max-w-2xl">
        <Input
          type="text"
          placeholder={`Enter ${searchMode} name...`}
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

      {/* Sort Dropdown + Results Count */}
      {urlQuery && (pagination || isLoading) && (
        <div className="flex items-center justify-between">
          <p className="text-muted-foreground">
            {isLoading ? (
              "Searching..."
            ) : (
              <>
                Showing {startIndex}-{endIndex} of {pagination?.total || 0}{" "}
                results for &ldquo;{urlQuery}&rdquo;
              </>
            )}
          </p>

          {!isLoading && (
            <div className="flex items-center gap-2">
              <ArrowUpDown className="w-4 h-4 text-muted-foreground" />
              <Select value={urlSort} onValueChange={handleSortChange}>
                <SelectTrigger className="w-[180px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {sortOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div ref={columnToggleCallback} />
            </div>
          )}
        </div>
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
      {error &&
        (searchMode === "comic" && !comicsConfigured ? (
          <div className="text-center py-12">
            <Settings className="w-12 h-12 text-muted-foreground/50 mx-auto mb-4" />
            <p className="text-muted-foreground text-lg">
              Comic Vine API key required
            </p>
            <p className="text-muted-foreground/70 text-sm mt-2">
              To search for comics, add your Comic Vine API key in{" "}
              <Link
                to="/settings"
                className="text-primary underline underline-offset-2"
              >
                Settings &rarr; API
              </Link>
            </p>
          </div>
        ) : (
          <div className="text-center py-12">
            <p className="text-red-600 text-lg">Search failed</p>
            <p className="text-muted-foreground text-sm mt-2">
              {error.message}
            </p>
          </div>
        ))}

      {/* No Results State */}
      {!isLoading && !error && urlQuery && searchResults.length === 0 && (
        <div className="text-center py-12">
          <p className="text-muted-foreground text-lg">
            No results found for &ldquo;{urlQuery}&rdquo;
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
            contentType={searchMode}
            columnToggleContainer={columnToggleEl}
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
            Enter a search term to find{" "}
            {searchMode === "manga" ? "manga" : "comics"}
          </p>
          <p className="text-gray-400 text-sm mt-2">
            Search requires at least 3 characters
          </p>
        </div>
      )}
    </div>
  );
}
