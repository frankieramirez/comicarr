import { useState, useCallback } from "react";
import { useSearchParams, Link } from "react-router-dom";
import {
  Search as SearchIcon,
  ChevronLeft,
  ChevronRight,
  Settings,
} from "lucide-react";
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
import EmptyState from "@/components/ui/EmptyState";
import PageHeader, { Tab, TabRow } from "@/components/layout/PageHeader";
import { Kbd } from "@/components/ui/kbd";
import type { ContentType } from "@/types/entities";

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

const comicSortMapping: Record<string, string | null> = {
  relevance: null,
  year_desc: "start_year:desc",
  year_asc: "start_year:asc",
  issues_desc: "count_of_issues:desc",
  issues_asc: "count_of_issues:asc",
  name_asc: "name:asc",
  name_desc: "name:desc",
};

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

  const urlQuery = searchParams.get("q") || "";
  const urlPage = parseInt(searchParams.get("page") || "1") || 1;
  const urlSort = searchParams.get("sort") || "relevance";

  const rawType = searchParams.get("type");
  const urlType: ContentType | null =
    rawType === "manga" ? "manga" : rawType === "comic" ? "comic" : null;
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

  const comicApiSort = comicSortMapping[urlSort] ?? urlSort;
  const mangaApiSort = mangaSortMapping[urlSort] || "relevance";

  const comicSearch = useSearchComics(
    searchMode === "comic" ? urlQuery : "",
    urlPage,
    comicApiSort,
  );
  const mangaSearch = useSearchManga(
    searchMode === "manga" ? urlQuery : "",
    urlPage,
    mangaApiSort,
  );
  const activeSearch = searchMode === "manga" ? mangaSearch : comicSearch;
  const { data, isLoading, error } = activeSearch;
  const searchResults = data?.results || [];
  const pagination = data?.pagination;
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

  const totalPages = pagination
    ? Math.ceil(pagination.total / pagination.limit)
    : 0;
  const startIndex = pagination ? pagination.offset + 1 : 0;
  const endIndex = pagination
    ? pagination.offset + (pagination.returned ?? 0)
    : 0;

  const showBothTabs = comicsEnabled && mangaEnabled;

  return (
    <div className="-mx-4 sm:-mx-6 lg:-mx-8 -my-8 page-transition min-w-0 overflow-hidden">
      <PageHeader
        title="Search"
        meta={
          urlQuery
            ? isLoading
              ? `searching "${urlQuery}"…`
              : `${pagination?.total ?? 0} results for "${urlQuery}"`
            : "find comics and manga to add"
        }
      />

      {showBothTabs && (
        <TabRow>
          <Tab
            active={searchMode === "comic"}
            label="Comics"
            onClick={() => handleSearchModeChange("comic")}
          />
          <Tab
            active={searchMode === "manga"}
            label="Manga"
            onClick={() => handleSearchModeChange("manga")}
          />
        </TabRow>
      )}

      <div className="px-5 py-4 space-y-4">
        {/* Search form */}
        <form onSubmit={handleSearch} className="flex items-center gap-2">
          <div
            className="flex items-center gap-2 flex-1 max-w-2xl px-3 py-2 rounded-[5px] border bg-card"
            style={{ borderColor: "var(--border)" }}
          >
            <SearchIcon className="w-3.5 h-3.5 text-muted-foreground" />
            <input
              type="text"
              placeholder={`Search ${searchMode === "manga" ? "manga" : "comics"}…`}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="flex-1 bg-transparent outline-none text-[13px] placeholder:text-[var(--text-muted)]"
            />
            <Kbd>↵</Kbd>
          </div>
          <button
            type="submit"
            disabled={searchQuery.trim().length < 3}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-[5px] text-[12px] font-semibold disabled:opacity-60"
            style={{
              background: "var(--primary)",
              color: "var(--primary-foreground)",
            }}
          >
            <SearchIcon className="w-3.5 h-3.5" />
            Search
          </button>
        </form>

        {/* Sort + results meta */}
        {urlQuery && (pagination || isLoading) && !isLoading && (
          <div className="flex items-center justify-between gap-3">
            <div className="font-mono text-[11px] text-muted-foreground">
              showing {startIndex}–{endIndex} of {pagination?.total || 0}
            </div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-[10px] tracking-[0.1em] uppercase text-muted-foreground">
                sort
              </span>
              <Select value={urlSort} onValueChange={handleSortChange}>
                <SelectTrigger className="h-7 text-[11px] w-[160px]">
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
          </div>
        )}

        {/* Loading */}
        {isLoading && (
          <div className="space-y-2">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        )}

        {/* Errors */}
        {error &&
          (searchMode === "comic" && !comicsConfigured ? (
            <EmptyState
              variant="custom"
              icon={Settings}
              eyebrow="PROVIDER · NOT CONFIGURED"
              title="Comic Vine API key required"
              description="Add a Comic Vine API key in Settings → API to search comics."
              action={{ label: "Open settings", to: "/settings" }}
            />
          ) : (
            <EmptyState
              variant="custom"
              eyebrow="SEARCH · ERROR"
              title="Search failed"
              description={error.message}
            />
          ))}

        {/* No results */}
        {!isLoading && !error && urlQuery && searchResults.length === 0 && (
          <EmptyState
            variant="search"
            eyebrow="SEARCH · NO MATCH"
            description={`No results for "${urlQuery}". Try a different query or check spelling.`}
          />
        )}

        {/* Results */}
        {!isLoading && !error && searchResults.length > 0 && (
          <div>
            <SearchResultsTable
              results={searchResults}
              currentSort={urlSort}
              onSortChange={handleSortChange}
              contentType={searchMode}
              columnToggleContainer={columnToggleEl}
            />

            {totalPages > 1 && (
              <div
                className="flex items-center justify-between mt-4 pt-3 border-t font-mono text-[11px] text-muted-foreground"
                style={{ borderColor: "var(--border)" }}
              >
                <button
                  type="button"
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded border disabled:opacity-50"
                  style={{ borderColor: "var(--border)" }}
                  onClick={() => handlePageChange(urlPage - 1)}
                  disabled={urlPage === 1}
                >
                  <ChevronLeft className="w-3 h-3" />
                  prev
                </button>
                <span>
                  page {urlPage} / {totalPages}
                </span>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded border disabled:opacity-50"
                  style={{ borderColor: "var(--border)" }}
                  onClick={() => handlePageChange(urlPage + 1)}
                  disabled={urlPage >= totalPages}
                >
                  next
                  <ChevronRight className="w-3 h-3" />
                </button>
              </div>
            )}
          </div>
        )}

        {/* Initial empty state */}
        {!urlQuery && (
          <EmptyState
            variant="custom"
            icon={SearchIcon}
            eyebrow="SEARCH · READY"
            title={`Find ${searchMode === "manga" ? "manga" : "comics"} to add`}
            description="Type at least 3 characters to search across your configured providers."
          />
        )}
      </div>

      {/* Hidden link for config navigation used by error branches */}
      <Link to="/settings" className="sr-only">
        settings
      </Link>
    </div>
  );
}
