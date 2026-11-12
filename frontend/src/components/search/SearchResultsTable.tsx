import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, ExternalLink, ImageOff } from "lucide-react";
import SearchAddButton from "./SearchAddButton";
import {
  SOURCE_LABELS,
  getCoverUrl,
  isSafeUrl,
  knownCount,
  knownYear,
} from "./searchResultUtils";
import { encodeRowId } from "@/components/data-table/rowId";
import type { SearchResult, ContentType } from "@/types";

/** Provider names as the meta line spells them out. */
const SOURCE_NAMES: Record<string, string> = {
  comicvine: "ComicVine",
  metron: "Metron",
  mangadex: "MangaDex",
  mal: "MyAnimeList",
};

function CoverThumbnail({ comic }: { comic: SearchResult }) {
  const [imageError, setImageError] = useState(false);
  const [isLoaded, setIsLoaded] = useState(false);

  const imageUrl = getCoverUrl(comic);

  if (!imageUrl || imageError) {
    return (
      <div className="flex h-12 w-9 shrink-0 items-center justify-center rounded-sm bg-surface-2">
        <ImageOff className="w-3.5 h-3.5 text-muted-foreground/50" />
      </div>
    );
  }

  return (
    <div className="h-12 w-9 shrink-0 overflow-hidden rounded-sm bg-surface-2">
      <img
        src={imageUrl}
        alt={comic.name}
        className={`w-full h-full object-cover transition-opacity duration-200 ${
          isLoaded ? "opacity-100" : "opacity-0"
        }`}
        loading="lazy"
        onLoad={() => setIsLoaded(true)}
        onError={() => setImageError(true)}
      />
    </div>
  );
}

interface SearchResultsTableProps {
  results: SearchResult[];
  contentType: ContentType;
}

/**
 * v2 "Add a series" results: cover, title, one meta line, and one action.
 * A series already in the library links to it instead of offering Add.
 */
export default function SearchResultsTable({
  results,
  contentType,
}: SearchResultsTableProps) {
  const unit = contentType === "manga" ? "chapters" : "issues";

  return (
    <div data-testid="search-results-table" className="px-4 md:px-8">
      {results.map((comic) => {
        const id = comic.comicid ?? comic.id;
        // A manga match is stored under its library ID, not the provider's.
        const libraryId =
          (typeof comic.haveit === "object" && comic.haveit?.comicid) || id;
        const source = comic.metadata_source ?? "";
        const sourceName =
          SOURCE_NAMES[source] ?? SOURCE_LABELS[source] ?? null;
        const count = knownCount(comic.issues ?? comic.count_of_issues);
        const year = knownYear(comic.comicyear);
        const publisher =
          comic.publisher && comic.publisher !== "Unknown"
            ? comic.publisher
            : null;
        const meta = [
          publisher,
          year,
          count != null ? `${count} ${unit}` : null,
          sourceName,
        ].filter((part): part is string => part != null);

        return (
          <div
            key={encodeRowId([id, comic.name, comic.comicyear])}
            data-testid="search-result-row"
            className="grid min-h-[72px] grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-3 border-b border-border-subtle py-3 md:gap-4"
          >
            <CoverThumbnail comic={comic} />
            <div className="min-w-0" data-grid-title="">
              <div className="flex min-w-0 items-center gap-1.5">
                <span className="truncate text-[14px] font-medium text-foreground">
                  {comic.name}
                </span>
                {comic.url && isSafeUrl(comic.url) && (
                  <a
                    href={comic.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="shrink-0 text-muted-foreground hover:text-foreground"
                    aria-label={`Open ${comic.name} on provider site`}
                  >
                    <ExternalLink className="size-3" />
                  </a>
                )}
              </div>
              {meta.length > 0 && (
                <div
                  data-testid="phone-row-id"
                  className="mt-0.5 truncate text-[13px] text-foreground-2"
                >
                  {meta.map((part, index) => (
                    <Fragment key={part}>
                      {index > 0 && " · "}
                      <span>{part}</span>
                    </Fragment>
                  ))}
                </div>
              )}
            </div>
            <div className="flex items-center justify-end gap-3">
              {comic.in_library && libraryId ? (
                <>
                  <span className="hidden items-center gap-1.5 text-[13px] text-foreground sm:inline-flex">
                    <span
                      aria-hidden
                      className="size-1.5 rounded-full bg-[var(--status-active)]"
                    />
                    In library
                  </span>
                  <Link
                    to={`/library/${libraryId}`}
                    aria-label={`Open ${comic.name}`}
                    className="inline-flex items-center gap-0.5 text-[13px] font-medium text-foreground hover:text-foreground-2"
                  >
                    Open
                    <ChevronRight className="size-3.5 text-muted-foreground" />
                  </Link>
                </>
              ) : (
                <SearchAddButton comic={comic} contentType={contentType} />
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
