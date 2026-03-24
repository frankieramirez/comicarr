import { useState, useRef, useCallback, useEffect } from "react";
import { Search, Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useFindStoryArc } from "@/hooks/useArcSearch";
import ArcSearchResultCard from "./ArcSearchResultCard";

interface ArcSearchProps {
  searchInputRef?: React.RefObject<HTMLInputElement | null>;
}

export default function ArcSearch({ searchInputRef }: ArcSearchProps) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(null);

  const { data: results, isLoading } = useFindStoryArc(debouncedQuery);

  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, []);

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setQuery(value);

    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
    debounceRef.current = setTimeout(() => {
      setDebouncedQuery(value);
    }, 400);
  }, []);

  return (
    <div className="space-y-4">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
        <Input
          ref={searchInputRef}
          type="text"
          placeholder="Search story arcs on ComicVine..."
          value={query}
          onChange={handleChange}
          className="pl-10"
        />
        {isLoading && (
          <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 animate-spin text-muted-foreground" />
        )}
      </div>

      {results && results.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {results.map((result) => (
            <ArcSearchResultCard key={result.cvarcid} result={result} />
          ))}
        </div>
      )}

      {debouncedQuery.length > 2 && !isLoading && results?.length === 0 && (
        <p className="text-sm text-muted-foreground text-center py-6">
          No story arcs found for &ldquo;{debouncedQuery}&rdquo;
        </p>
      )}
    </div>
  );
}
