import { useState } from "react";
import {
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
  ImageOff,
  ExternalLink,
} from "lucide-react";
import SearchAddButton from "./SearchAddButton";
import {
  SOURCE_LABELS,
  getCoverUrl,
  getDescription,
  isSafeUrl,
  truncate,
} from "./searchResultUtils";
import { DESKTOP_COL } from "@/components/data-table/gridColumns";
import { encodeRowId } from "@/components/data-table/rowId";
import type { SearchResult, ContentType } from "@/types";

const SORT_COLUMN_MAP: Record<string, { asc: string; desc: string }> = {
  series: { asc: "name_asc", desc: "name_desc" },
  year: { asc: "year_asc", desc: "year_desc" },
  issues: { asc: "issues_asc", desc: "issues_desc" },
};

function getColumnSort(
  columnId: string,
  currentSort: string,
): "asc" | "desc" | false {
  const mapping = SORT_COLUMN_MAP[columnId];
  if (!mapping) return false;
  if (currentSort === mapping.asc) return "asc";
  if (currentSort === mapping.desc) return "desc";
  return false;
}

function CoverThumbnail({ comic }: { comic: SearchResult }) {
  const [imageError, setImageError] = useState(false);
  const [isLoaded, setIsLoaded] = useState(false);

  const imageUrl = getCoverUrl(comic);

  if (!imageUrl || imageError) {
    return (
      <div
        className="w-10 h-[56px] rounded-[3px] border flex items-center justify-center shrink-0"
        style={{ borderColor: "var(--border)", background: "var(--card)" }}
      >
        <ImageOff className="w-3.5 h-3.5 text-muted-foreground/50" />
      </div>
    );
  }

  return (
    <div
      className="w-10 h-[56px] rounded-[3px] overflow-hidden shrink-0 border"
      style={{ borderColor: "var(--border)", background: "var(--card)" }}
    >
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

function SortHeader({
  columnId,
  title,
  currentSort,
  onSortChange,
}: {
  columnId: string;
  title: string;
  currentSort: string;
  onSortChange: (sort: string) => void;
}) {
  const mapping = SORT_COLUMN_MAP[columnId];
  if (!mapping) return <span>{title}</span>;
  const sortState = getColumnSort(columnId, currentSort);
  const sortAnnouncement =
    sortState === "asc"
      ? "sorted ascending"
      : sortState === "desc"
        ? "sorted descending"
        : null;

  const handleClick = () => {
    if (sortState === false) onSortChange(mapping.desc);
    else if (sortState === "desc") onSortChange(mapping.asc);
    else onSortChange(mapping.desc);
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className="inline-flex items-center gap-1 hover:text-foreground transition-colors"
    >
      <span>{title}</span>
      {sortState === "asc" ? (
        <ChevronUp className="w-3 h-3" aria-hidden />
      ) : sortState === "desc" ? (
        <ChevronDown className="w-3 h-3" aria-hidden />
      ) : (
        <ChevronsUpDown className="w-3 h-3 opacity-50" aria-hidden />
      )}
      {sortAnnouncement ? (
        <span className="sr-only">{sortAnnouncement}</span>
      ) : null}
    </button>
  );
}

interface SearchResultsTableProps {
  results: SearchResult[];
  currentSort: string;
  onSortChange: (sort: string) => void;
  contentType: ContentType;
  /** Unused — retained for API compatibility. */
  columnToggleContainer?: HTMLElement | null;
}

const LIST_ROW_COLS =
  "grid-cols-[40px_minmax(0,1fr)_auto] md:grid-cols-[40px_56px_minmax(0,1fr)_160px_70px_70px_100px]";

export default function SearchResultsTable({
  results,
  currentSort,
  onSortChange,
  contentType,
}: SearchResultsTableProps) {
  const isManga = contentType === "manga";
  const issuesLabel = isManga ? "Chapters" : "Issues";
  const publisherLabel = isManga ? "Author" : "Publisher";

  return (
    <div data-testid="search-results-table">
      {/* Header — sticky inside the page's results scroll region. */}
      <div
        className={`sticky top-0 z-10 grid items-center gap-3 px-5 py-2 font-mono text-[10px] tracking-[0.08em] uppercase border-b ${LIST_ROW_COLS}`}
        style={{
          borderColor: "var(--border)",
          background: "var(--background)",
          color: "var(--text-muted)",
        }}
      >
        <div className={DESKTOP_COL} />
        <div />
        <div>
          <SortHeader
            columnId="series"
            title="Series"
            currentSort={currentSort}
            onSortChange={onSortChange}
          />
        </div>
        <div className={DESKTOP_COL}>{publisherLabel}</div>
        <div className={DESKTOP_COL}>
          <SortHeader
            columnId="year"
            title="Year"
            currentSort={currentSort}
            onSortChange={onSortChange}
          />
        </div>
        <div className={DESKTOP_COL}>
          <SortHeader
            columnId="issues"
            title={issuesLabel}
            currentSort={currentSort}
            onSortChange={onSortChange}
          />
        </div>
        <div />
      </div>

      {/* Rows */}
      {results.map((comic, idx) => {
        const description = getDescription(comic);
        const sourceLabel = SOURCE_LABELS[comic.metadata_source ?? ""] ?? null;
        const issues = comic.issues ?? comic.count_of_issues;
        return (
          <div
            key={encodeRowId([
              comic.comicid ?? comic.id,
              comic.name,
              comic.comicyear,
            ])}
            data-testid="search-result-row"
            className={`grid items-center gap-3 px-5 py-2.5 border-b hover:bg-secondary/30 transition-colors text-[12px] ${LIST_ROW_COLS}`}
            style={{
              borderColor: "var(--border)",
            }}
          >
            <div
              className={`${DESKTOP_COL} font-mono text-[10px]`}
              style={{ color: "var(--text-muted)" }}
            >
              {String(idx + 1).padStart(2, "0")}
            </div>
            <CoverThumbnail comic={comic} />
            <div className="min-w-0" data-grid-title="">
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="font-medium truncate text-[13px]">
                  {comic.name}
                </span>
                {(comic.comicyear ||
                  (comic.publisher && comic.publisher !== "Unknown")) && (
                  <span
                    data-testid="phone-row-id"
                    className="hidden max-md:inline shrink-0 font-mono text-[10px]"
                    style={{ color: "var(--muted-foreground)" }}
                  >
                    {comic.comicyear ? ` · ${comic.comicyear}` : ""}
                    {comic.publisher && comic.publisher !== "Unknown"
                      ? ` · ${comic.publisher}`
                      : ""}
                  </span>
                )}
                {sourceLabel && (
                  <span
                    className="shrink-0 font-mono text-[9px] tracking-[0.05em] uppercase px-1.5 py-0.5 rounded-[3px] border"
                    style={{
                      borderColor: "var(--border)",
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
                    onClick={(e) => e.stopPropagation()}
                    className="shrink-0 text-muted-foreground hover:text-foreground"
                    aria-label={`Open ${comic.name} on provider site`}
                  >
                    <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>
              {description && (
                <div
                  className="text-[11.5px] truncate mt-0.5"
                  style={{ color: "var(--muted-foreground)" }}
                >
                  {truncate(description, 140)}
                </div>
              )}
            </div>
            <div
              className={`${DESKTOP_COL} truncate`}
              style={{ color: "var(--muted-foreground)" }}
            >
              {comic.publisher && comic.publisher !== "Unknown"
                ? comic.publisher
                : "—"}
            </div>
            <div
              className={`${DESKTOP_COL} font-mono text-[11px]`}
              style={{ color: "var(--muted-foreground)" }}
            >
              {comic.comicyear || "—"}
            </div>
            <div className={`${DESKTOP_COL} font-mono text-[11px]`}>
              {issues !== undefined ? issues : "—"}
            </div>
            <div className="flex justify-end">
              <SearchAddButton comic={comic} contentType={contentType} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
