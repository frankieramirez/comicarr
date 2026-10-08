import { useState } from "react";
import { ExternalLink, ImageOff } from "lucide-react";
import SearchAddButton from "./SearchAddButton";
import {
  SOURCE_LABELS,
  getCardCoverUrl,
  getCoverUrl,
  getDescription,
  isSafeUrl,
  knownCount,
  knownYear,
  truncate,
} from "./searchResultUtils";
import type { SearchResult, ContentType } from "@/types";

interface SearchResultsGridProps {
  results: SearchResult[];
  contentType: ContentType;
}

export default function SearchResultsGrid({
  results,
  contentType,
}: SearchResultsGridProps) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4 px-5 py-4">
      {results.map((comic, idx) => (
        <SearchResultCard
          key={comic.comicid ?? comic.id ?? idx}
          comic={comic}
          contentType={contentType}
        />
      ))}
    </div>
  );
}

function SearchResultCard({
  comic,
  contentType,
}: {
  comic: SearchResult;
  contentType: ContentType;
}) {
  // Try the large cover first, then the list thumbnail, then the placeholder.
  const coverCandidates = [
    ...new Set([getCardCoverUrl(comic), getCoverUrl(comic)]),
  ].filter((url): url is string => !!url);
  const description = getDescription(comic);
  const sourceLabel = SOURCE_LABELS[comic.metadata_source ?? ""] ?? null;
  const issues = knownCount(comic.issues ?? comic.count_of_issues);
  const issuesLabel = contentType === "manga" ? "ch" : "iss";
  const publisher =
    comic.publisher && comic.publisher !== "Unknown" ? comic.publisher : null;
  const meta = [
    knownYear(comic.comicyear),
    issues !== null ? `${issues} ${issuesLabel}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      data-testid="search-result-card"
      className="bg-card rounded-lg border overflow-hidden flex flex-col h-full"
    >
      <div className="aspect-[2/3] bg-muted relative overflow-hidden shrink-0">
        {/* Keyed by its candidates so new cover URLs start a fresh attempt
            instead of inheriting the previous fallback position. */}
        <CardCover
          key={coverCandidates.join("|")}
          candidates={coverCandidates}
          alt={comic.name}
        />

        {sourceLabel && (
          <span
            className="absolute top-2 left-2 font-mono text-[9px] tracking-[0.05em] uppercase px-1.5 py-0.5 rounded-[3px] border"
            style={{
              borderColor: "var(--border)",
              background: "var(--background)",
              color: "var(--muted-foreground)",
            }}
          >
            {sourceLabel}
          </span>
        )}

        {comic.url && isSafeUrl(comic.url) && (
          <a
            href={comic.url}
            target="_blank"
            rel="noopener noreferrer"
            className="absolute top-2 right-2 p-1 rounded-[3px] border text-muted-foreground hover:text-foreground"
            style={{
              borderColor: "var(--border)",
              background: "var(--background)",
            }}
            aria-label={`Open ${comic.name} on provider site`}
          >
            <ExternalLink className="w-3 h-3" />
          </a>
        )}
      </div>

      <div className="p-3 flex flex-col flex-grow gap-2">
        <div className="flex-grow min-w-0">
          <h3
            className="font-semibold text-[13px] line-clamp-2 leading-tight"
            title={comic.name}
          >
            {comic.name}
          </h3>
          {meta && <p className="mono-meta mt-1">{meta}</p>}
          {publisher && (
            <p className="text-[11.5px] text-muted-foreground mt-0.5 truncate">
              {publisher}
            </p>
          )}
          {description && (
            <p
              className="text-[11.5px] text-muted-foreground mt-1.5 line-clamp-2"
              title={truncate(description, 400)}
            >
              {description}
            </p>
          )}
        </div>
        <SearchAddButton
          comic={comic}
          contentType={contentType}
          className="w-full"
        />
      </div>
    </div>
  );
}

function CardCover({ candidates, alt }: { candidates: string[]; alt: string }) {
  const [failedCount, setFailedCount] = useState(0);
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null);

  const imageUrl = candidates[failedCount];
  if (!imageUrl) {
    return (
      <div className="w-full h-full flex items-center justify-center text-muted-foreground/50">
        <ImageOff className="w-8 h-8" />
      </div>
    );
  }

  return (
    <img
      src={imageUrl}
      alt={alt}
      className={`w-full h-full object-cover transition-opacity duration-200 ${
        loadedUrl === imageUrl ? "opacity-100" : "opacity-0"
      }`}
      loading="lazy"
      onLoad={() => setLoadedUrl(imageUrl)}
      onError={() => setFailedCount((n) => n + 1)}
    />
  );
}
