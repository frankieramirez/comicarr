import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Search as SearchIcon, ChevronLeft, ChevronRight } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useSearchComics } from "@/hooks/useSearch";
import SearchResultsTable from "@/components/search/SearchResultsTable";
import { Skeleton } from "@/components/ui/skeleton";

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  // Get parameters from URL
  const urlQuery = searchParams.get("q") || "";
  const urlPage = parseInt(searchParams.get("page") || "1") || 1;
  const urlSort = searchParams.get("sort") || "year_desc";

  // Initialize search query from URL parameter
  const [searchQuery, setSearchQuery] = useState(urlQuery);

  // Map frontend sort values to ComicVine API format
  const sortMapping: Record<string, string> = {
    year_desc: "start_year:desc",
    year_asc: "start_year:asc",
    issues_desc: "count_of_issues:desc",
    issues_asc: "count_of_issues:asc",
    name_asc: "name:asc",
    name_desc: "name:desc",
  };

  const apiSort = sortMapping[urlSort] || urlSort;

  // Use server-side pagination
  const { data, isLoading, error } = useSearchComics(urlQuery, urlPage, apiSort);
  const searchResults = data?.results || [];
  const pagination = data?.pagination;

  const handleSearch = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (searchQuery.trim().length > 2) {
      setSearchParams({ q: searchQuery.trim(), page: "1", sort: urlSort });
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

  return (
    <div className="space-y-4 page-transition">
      {/* Header with search form */}
      <div className="flex flex-col lg:flex-row lg:items-center lg:gap-6">
        <h1 className="text-3xl font-bold mb-3 lg:mb-0 lg:whitespace-nowrap">
          Search Comics
        </h1>
        <form onSubmit={handleSearch} className="flex gap-2 flex-1 max-w-2xl">
          <Input
            type="text"
            placeholder="Enter comic name..."
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
      </div>

      {/* Loading State */}
      {isLoading && (
        <div className="rounded-lg border-card-border bg-card card-shadow overflow-hidden">
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
          {/* Results count */}
          <div className="mb-4">
            <p className="text-gray-600 dark:text-gray-400">
              Showing {startIndex}-{endIndex} of {pagination?.total || 0} result
              {pagination?.total !== 1 ? "s" : ""} for "{urlQuery}"
            </p>
          </div>

          <SearchResultsTable
            results={searchResults}
            currentSort={urlSort}
            onSortChange={handleSortChange}
          />

          {/* Pagination Controls */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-8 pt-6 border-t border-gray-200 dark:border-gray-700">
              <Button
                variant="outline"
                onClick={() => handlePageChange(urlPage - 1)}
                disabled={urlPage === 1}
              >
                <ChevronLeft className="w-4 h-4 mr-2" />
                Previous
              </Button>

              <span className="text-sm text-gray-600 dark:text-gray-400">
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
            Enter a search term to find comics
          </p>
          <p className="text-gray-400 text-sm mt-2">
            Search requires at least 3 characters
          </p>
        </div>
      )}
    </div>
  );
}
