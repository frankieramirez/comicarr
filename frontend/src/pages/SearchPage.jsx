import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Search as SearchIcon, ChevronLeft, ChevronRight } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useSearchComics } from '@/hooks/useSearch';
import ComicCard from '@/components/search/ComicCard';
import { Skeleton } from '@/components/ui/skeleton';

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [searchQuery, setSearchQuery] = useState('');

  // Get parameters from URL
  const urlQuery = searchParams.get('q') || '';
  const urlPage = parseInt(searchParams.get('page')) || 1;
  const urlSort = searchParams.get('sort') || 'start_year:desc';  // ComicVine API format

  // Map frontend sort values to ComicVine API format
  const sortMapping = {
    'year_desc': 'start_year:desc',
    'year_asc': 'start_year:asc',
    'issues_desc': 'count_of_issues:desc',
    'issues_asc': 'count_of_issues:asc',
    'name_asc': 'name:asc',
    'name_desc': 'name:desc',
  };

  const apiSort = sortMapping[urlSort] || urlSort;

  // Use server-side pagination
  const { data, isLoading, error } = useSearchComics(urlQuery, urlPage, apiSort);
  const searchResults = data?.results || [];
  const pagination = data?.pagination;

  // Initialize search query from URL on mount
  useEffect(() => {
    if (urlQuery) {
      setSearchQuery(urlQuery);
    }
  }, []);

  const handleSearch = (e) => {
    e.preventDefault();
    if (searchQuery.trim().length > 2) {
      setSearchParams({ q: searchQuery.trim(), page: '1', sort: urlSort });
    }
  };

  const handlePageChange = (newPage) => {
    const params = Object.fromEntries(searchParams);
    params.page = newPage.toString();
    setSearchParams(params);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleSortChange = (value) => {
    const params = Object.fromEntries(searchParams);
    params.sort = value;
    params.page = '1'; // Reset to page 1 when sort changes
    setSearchParams(params);
  };

  // Calculate pagination info from server metadata
  const totalPages = pagination ? Math.ceil(pagination.total / pagination.limit) : 0;
  const startIndex = pagination ? pagination.offset + 1 : 0;
  const endIndex = pagination ? pagination.offset + pagination.returned : 0;

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
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-6">
          {[...Array(12)].map((_, i) => (
            <div key={i} className="flex flex-col h-full">
              <Skeleton className="aspect-[2/3] w-full flex-shrink-0" />
              <div className="p-3 flex flex-col flex-grow">
                <Skeleton className="h-3.5 w-full mb-1" />
                <Skeleton className="h-3 w-1/3 mb-2" />
                <Skeleton className="h-3 w-2/3 mb-3" />
                <Skeleton className="h-8 w-full mt-auto" />
              </div>
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
          <p className="text-muted-foreground text-lg">No results found for "{urlQuery}"</p>
          <p className="text-gray-400 text-sm mt-2">
            Try a different search term or check your spelling.
          </p>
        </div>
      )}

      {/* Results Grid */}
      {!isLoading && !error && searchResults.length > 0 && (
        <div>
          {/* Combined results count and sort control */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
            <p className="text-gray-600 dark:text-gray-400">
              Showing {startIndex}-{endIndex} of {pagination?.total || 0} result{pagination?.total !== 1 ? 's' : ''} for "{urlQuery}"
            </p>

            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-600 dark:text-gray-400 whitespace-nowrap">
                Sort by:
              </span>
              <Select value={urlSort} onValueChange={handleSortChange}>
                <SelectTrigger className="w-48" aria-label="Sort search results">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="year_desc">Year (Newest First)</SelectItem>
                  <SelectItem value="year_asc">Year (Oldest First)</SelectItem>
                  <SelectItem value="issues_desc">Issue Count (Most First)</SelectItem>
                  <SelectItem value="issues_asc">Issue Count (Least First)</SelectItem>
                  <SelectItem value="name_asc">Name (A-Z)</SelectItem>
                  <SelectItem value="name_desc">Name (Z-A)</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-6">
            {searchResults.map((comic) => (
              <ComicCard key={comic.comicid} comic={comic} />
            ))}
          </div>

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
          <p className="text-muted-foreground text-lg">Enter a search term to find comics</p>
          <p className="text-gray-400 text-sm mt-2">
            Search requires at least 3 characters
          </p>
        </div>
      )}
    </div>
  );
}
