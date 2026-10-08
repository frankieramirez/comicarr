import { useState, useRef, useCallback, useEffect } from "react";
import { useFindStoryArc } from "@/hooks/useArcSearch";
import { useContentSources } from "@/hooks/useContentSources";
import { Button } from "@/components/ui/button";
import FilterField from "@/components/ui/FilterField";
import EmptyState from "@/components/ui/EmptyState";
import ArcSearchResultCard from "./ArcSearchResultCard";
import { Settings } from "lucide-react";

interface ArcSearchProps {
  searchInputRef?: React.RefObject<HTMLInputElement | null>;
  formRef?: React.RefObject<HTMLFormElement | null>;
}

export default function ArcSearch({ searchInputRef, formRef }: ArcSearchProps) {
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(null);
  const localFormRef = useRef<HTMLFormElement>(null);
  const resolvedFormRef = formRef ?? localFormRef;
  const { comicsConfigured, isLoaded } = useContentSources();

  const {
    data: results,
    isLoading,
    isFetching,
    error,
  } = useFindStoryArc(activeQuery);

  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, []);

  const commitSearch = useCallback((value: string) => {
    const trimmed = value.trim();
    if (trimmed.length > 2) {
      setActiveQuery(trimmed);
    }
  }, []);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const value = e.target.value;
      setQuery(value);

      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
      debounceRef.current = setTimeout(() => {
        commitSearch(value);
      }, 400);
    },
    [commitSearch],
  );

  const handleSubmit = useCallback(
    (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
        debounceRef.current = null;
      }
      commitSearch(query);
    },
    [commitSearch, query],
  );

  const searching = (isLoading || isFetching) && activeQuery.length > 2;
  const showResults = !!results && results.length > 0;
  const showEmpty =
    activeQuery.length > 2 && !searching && !error && results?.length === 0;
  const providerUnavailable = isLoaded && !comicsConfigured;

  return (
    <div className="space-y-4">
      <form
        ref={resolvedFormRef}
        onSubmit={handleSubmit}
        className="flex items-center gap-2 flex-1 min-w-[260px] max-w-[560px]"
      >
        <FilterField
          ref={searchInputRef}
          placeholder="Search story arcs on ComicVine…"
          aria-label="Search story arcs"
          value={query}
          onChange={handleChange}
          shortcut="↵"
          loading={searching}
          widthCap="full"
        />
        <Button
          type="submit"
          size="toolbar"
          disabled={query.trim().length < 3}
          className="font-semibold"
        >
          Search
        </Button>
      </form>

      {error && activeQuery.length > 2 && (
        <div>
          {providerUnavailable ? (
            <EmptyState
              variant="custom"
              icon={Settings}
              eyebrow="PROVIDER · NOT CONFIGURED"
              title="Comic Vine API key required"
              description="Add a Comic Vine API key in Settings → API to search story arcs."
              action={{ label: "Open settings", to: "/settings" }}
            />
          ) : (
            <EmptyState
              variant="custom"
              eyebrow="SEARCH · ERROR"
              title="Story arc search failed"
              description={error.message}
            />
          )}
        </div>
      )}

      {showResults && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {results.map((result) => (
            <ArcSearchResultCard key={result.cvarcid} result={result} />
          ))}
        </div>
      )}

      {showEmpty && (
        <p className="text-[12px] text-muted-foreground text-center py-6">
          No story arcs found for &ldquo;{activeQuery}&rdquo;
        </p>
      )}
    </div>
  );
}
