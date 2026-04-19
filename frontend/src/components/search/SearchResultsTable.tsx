import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
  Plus,
  Check,
  Loader2,
  ImageOff,
  ExternalLink,
} from "lucide-react";
import { useAddComic, useAddManga } from "@/hooks/useSearch";
import { useToast } from "@/components/ui/toast";
import type { SearchResult, ContentType } from "@/types";

const SOURCE_LABELS: Record<string, string> = {
  comicvine: "CV",
  metron: "Metron",
  mangadex: "MangaDex",
  mal: "MAL",
};

const htmlParser = new DOMParser();

function stripHtml(html: string): string {
  const doc = htmlParser.parseFromString(html, "text/html");
  return doc.body.textContent || "";
}

function isSafeUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

function getDescription(comic: SearchResult): string | null {
  if (comic.deck && comic.deck !== "None") return comic.deck;
  if (comic.description) return stripHtml(comic.description);
  return null;
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + "\u2026";
}

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

  const imageUrl = comic.comicthumb || comic.image || comic.comicimage;

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

interface AddByIdEventDetail {
  comicid: string;
  status: "success" | "failure";
  message?: string;
}

function AddButton({
  comic,
  contentType,
}: {
  comic: SearchResult;
  contentType: ContentType;
}) {
  const [isAdded, setIsAdded] = useState(comic.in_library ?? false);
  const [isProcessing, setIsProcessing] = useState(false);
  const addComicMutation = useAddComic();
  const addMangaMutation = useAddManga();
  const { addToast } = useToast();
  const navigate = useNavigate();
  const comicIdRef = useRef<string | null>(null);

  const isManga = contentType === "manga";
  const itemLabel = isManga ? "Manga" : "Comic";

  useEffect(() => {
    if (!isProcessing || !comicIdRef.current) return;
    let cancelled = false;

    const handleAddById = (event: CustomEvent<string>) => {
      if (cancelled) return;
      try {
        const data: AddByIdEventDetail = JSON.parse(event.detail);
        if (data.comicid === comicIdRef.current) {
          if (data.status === "success") {
            navigate(`/library/${comicIdRef.current}`);
            setIsProcessing(false);
            comicIdRef.current = null;
          } else if (data.status === "failure") {
            addToast({
              type: "error",
              title: "Failed to Add Series",
              description:
                data.message || "An error occurred while adding the series.",
            });
            setIsProcessing(false);
            setIsAdded(false);
            comicIdRef.current = null;
          }
        }
      } catch (error) {
        console.error("Error parsing addbyid event:", error);
      }
    };

    window.addEventListener("comic-added", handleAddById as EventListener);
    return () => {
      cancelled = true;
      window.removeEventListener("comic-added", handleAddById as EventListener);
    };
  }, [isProcessing, navigate, addToast]);

  const handleAdd = async (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    try {
      comicIdRef.current = comic.comicid ?? comic.id ?? null;
      setIsProcessing(true);
      if (isManga)
        await addMangaMutation.mutateAsync(comic.comicid ?? comic.id);
      else await addComicMutation.mutateAsync(comic.comicid ?? comic.id);
      setIsAdded(true);
      addToast({
        type: "success",
        title: `Adding ${itemLabel}...`,
        description: `${comic.name} is being added to your library. Please wait...`,
        duration: 5000,
      });
    } catch (err) {
      setIsProcessing(false);
      setIsAdded(false);
      comicIdRef.current = null;
      addToast({
        type: "error",
        title: `Failed to Add ${itemLabel}`,
        description: err instanceof Error ? err.message : "Unknown error",
      });
    }
  };

  const base =
    "inline-flex items-center gap-1 px-2.5 py-1 rounded-[5px] border font-mono text-[11px] transition-colors";

  if (isAdded) {
    return (
      <button
        type="button"
        disabled
        className={base}
        style={{
          borderColor: "var(--border)",
          color: "var(--status-active)",
        }}
      >
        <Check className="w-3 h-3" />
        added
      </button>
    );
  }

  if (isProcessing) {
    return (
      <button
        type="button"
        disabled
        className={base}
        style={{
          borderColor: "var(--border)",
          color: "var(--muted-foreground)",
        }}
      >
        <Loader2 className="w-3 h-3 animate-spin" />
        adding…
      </button>
    );
  }

  const isPending = isManga
    ? addMangaMutation.isPending
    : addComicMutation.isPending;

  return (
    <button
      type="button"
      onClick={handleAdd}
      disabled={isPending}
      className={`${base} hover:bg-[color-mix(in_oklab,var(--primary)_14%,transparent)]`}
      style={{
        borderColor: "var(--primary)",
        color: "var(--primary)",
      }}
    >
      <Plus className="w-3 h-3" />
      {isPending ? "adding…" : "add"}
    </button>
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
  const ariaSort =
    sortState === "asc"
      ? ("ascending" as const)
      : sortState === "desc"
        ? ("descending" as const)
        : undefined;

  const handleClick = () => {
    if (sortState === false) onSortChange(mapping.desc);
    else if (sortState === "desc") onSortChange(mapping.asc);
    else onSortChange(mapping.desc);
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      aria-sort={ariaSort}
      className="inline-flex items-center gap-1 hover:text-foreground transition-colors"
    >
      <span>{title}</span>
      {sortState === "asc" ? (
        <ChevronUp className="w-3 h-3" />
      ) : sortState === "desc" ? (
        <ChevronDown className="w-3 h-3" />
      ) : (
        <ChevronsUpDown className="w-3 h-3 opacity-50" />
      )}
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

const GRID = "40px 56px 1fr 160px 70px 70px 100px";

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
    <div>
      {/* Header */}
      <div
        className="grid items-center gap-3 px-5 py-2 font-mono text-[10px] tracking-[0.08em] uppercase border-b"
        style={{
          gridTemplateColumns: GRID,
          borderColor: "var(--border)",
          color: "var(--text-muted)",
        }}
      >
        <div />
        <div />
        <div>
          <SortHeader
            columnId="series"
            title="Series"
            currentSort={currentSort}
            onSortChange={onSortChange}
          />
        </div>
        <div>{publisherLabel}</div>
        <div>
          <SortHeader
            columnId="year"
            title="Year"
            currentSort={currentSort}
            onSortChange={onSortChange}
          />
        </div>
        <div>
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
            key={comic.comicid ?? comic.id ?? idx}
            className="grid items-center gap-3 px-5 py-2.5 border-b hover:bg-secondary/30 transition-colors text-[12px]"
            style={{
              gridTemplateColumns: GRID,
              borderColor: "var(--border)",
            }}
          >
            <div
              className="font-mono text-[10px]"
              style={{ color: "var(--text-muted)" }}
            >
              {String(idx + 1).padStart(2, "0")}
            </div>
            <CoverThumbnail comic={comic} />
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="font-medium truncate text-[13px]">
                  {comic.name}
                </span>
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
              className="truncate"
              style={{ color: "var(--muted-foreground)" }}
            >
              {comic.publisher && comic.publisher !== "Unknown"
                ? comic.publisher
                : "—"}
            </div>
            <div
              className="font-mono text-[11px]"
              style={{ color: "var(--muted-foreground)" }}
            >
              {comic.comicyear || "—"}
            </div>
            <div className="font-mono text-[11px]">
              {issues !== undefined ? issues : "—"}
            </div>
            <div className="flex justify-end">
              <AddButton comic={comic} contentType={contentType} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
