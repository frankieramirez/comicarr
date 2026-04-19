import { useState, useRef, useCallback, useEffect } from "react";
import { useFindStoryArc } from "@/hooks/useArcSearch";
import FilterField from "@/components/ui/FilterField";
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
      <FilterField
        ref={searchInputRef}
        placeholder="Search story arcs on ComicVine…"
        aria-label="Search story arcs"
        value={query}
        onChange={handleChange}
        shortcut="/"
        loading={isLoading && query.length > 2}
      />

      {results && results.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {results.map((result) => (
            <ArcSearchResultCard key={result.cvarcid} result={result} />
          ))}
        </div>
      )}

      {debouncedQuery.length > 2 && !isLoading && results?.length === 0 && (
        <p className="text-[12px] text-muted-foreground text-center py-6">
          No story arcs found for &ldquo;{debouncedQuery}&rdquo;
        </p>
      )}
    </div>
  );
}
