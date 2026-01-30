import { useState } from 'react';
import { Search as SearchIcon } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { useSearchComics } from '@/hooks/useSearch';
import ComicCard from '@/components/search/ComicCard';
import { Skeleton } from '@/components/ui/skeleton';

export default function SearchPage() {
  const [searchQuery, setSearchQuery] = useState('');
  const [activeQuery, setActiveQuery] = useState('');

  const { data: searchResults = [], isLoading, error } = useSearchComics(activeQuery);

  const handleSearch = (e) => {
    e.preventDefault();
    if (searchQuery.trim().length > 2) {
      setActiveQuery(searchQuery.trim());
    }
  };

  return (
    <div className="space-y-6 page-transition">
      <div>
        <h1 className="text-3xl font-bold mb-2">Search Comics</h1>
        <p className="text-gray-600">
          Search for comics to add to your library
        </p>
      </div>

      {/* Search Form */}
      <form onSubmit={handleSearch} className="flex gap-2 max-w-2xl">
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

      {/* Search Results */}
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

      {error && (
        <div className="text-center py-12">
          <p className="text-red-600 text-lg">Search failed</p>
          <p className="text-muted-foreground text-sm mt-2">{error.message}</p>
        </div>
      )}

      {!isLoading && !error && activeQuery && searchResults.length === 0 && (
        <div className="text-center py-12">
          <p className="text-muted-foreground text-lg">No results found for "{activeQuery}"</p>
          <p className="text-gray-400 text-sm mt-2">
            Try a different search term or check your spelling.
          </p>
        </div>
      )}

      {!isLoading && !error && searchResults.length > 0 && (
        <div>
          <p className="text-gray-600 mb-4">
            Found {searchResults.length} result{searchResults.length !== 1 ? 's' : ''} for "{activeQuery}"
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-6">
            {searchResults.map((comic) => (
              <ComicCard key={comic.comicid} comic={comic} />
            ))}
          </div>
        </div>
      )}

      {!activeQuery && (
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
