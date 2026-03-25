import { useState, useEffect, useRef, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  useReactTable,
  getCoreRowModel,
  createColumnHelper,
  type VisibilityState,
} from "@tanstack/react-table";
import {
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
  Plus,
  Check,
  Loader2,
  ImageOff,
  ExternalLink,
  Settings2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { DataTable } from "@/components/data-table/DataTable";
import { useAddComic, useAddManga } from "@/hooks/useSearch";
import { useToast } from "@/components/ui/toast";
import type { SearchResult, ContentType } from "@/types";

const columnHelper = createColumnHelper<SearchResult>();

// Lazy-loaded cover thumbnail component
function CoverThumbnail({ comic }: { comic: SearchResult }) {
  const [imageError, setImageError] = useState(false);
  const [isLoaded, setIsLoaded] = useState(false);

  const imageUrl = comic.comicthumb || comic.image || comic.comicimage;

  if (!imageUrl || imageError) {
    return (
      <div className="w-10 h-14 bg-muted rounded flex items-center justify-center flex-shrink-0">
        <ImageOff className="w-4 h-4 text-muted-foreground/50" />
      </div>
    );
  }

  return (
    <div className="w-10 h-14 bg-muted rounded overflow-hidden flex-shrink-0">
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

const SOURCE_LABELS: Record<string, string> = {
  comicvine: "CV",
  metron: "Metron",
  mangadex: "MangaDex",
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

// Column visibility toggle for search results
function SearchColumnVisibility({
  columnVisibility,
  onToggle,
  isManga,
}: {
  columnVisibility: VisibilityState;
  onToggle: (columnId: string) => void;
  isManga: boolean;
}) {
  const toggleableColumns = [
    { id: "publisher", label: isManga ? "Author" : "Publisher" },
    { id: "seriesStatus", label: "Status" },
    { id: "contentRating", label: "Content Rating" },
  ];

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="icon" className="shadow-none">
          <Settings2 className="h-4 w-4" />
          <span className="sr-only">Toggle columns</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent side="bottom" align="end" className="w-[180px] p-2">
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground px-2 py-1">
            Toggle columns
          </p>
          {toggleableColumns.map((col) => (
            <button
              key={col.id}
              onClick={() => onToggle(col.id)}
              className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent"
            >
              <div
                className={`flex h-4 w-4 items-center justify-center rounded-sm border ${
                  columnVisibility[col.id] !== false
                    ? "bg-primary text-primary-foreground border-primary"
                    : "opacity-50"
                }`}
              >
                {columnVisibility[col.id] !== false && (
                  <Check className="h-3 w-3" />
                )}
              </div>
              <span>{col.label}</span>
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}

interface SearchResultsTableProps {
  results: SearchResult[];
  currentSort: string;
  onSortChange: (sort: string) => void;
  contentType: ContentType;
}

interface AddByIdEventDetail {
  comicid: string;
  status: "success" | "failure";
  message?: string;
}

// Map column IDs to API sort values
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

// Action cell component to handle add-to-library logic
function ActionCell({
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

  // Listen for SSE events when a comic is being added
  useEffect(() => {
    if (!isProcessing || !comicIdRef.current) return;
    let cancelled = false;

    const handleAddById = (event: CustomEvent<string>) => {
      if (cancelled) return;
      try {
        const data: AddByIdEventDetail = JSON.parse(event.detail);

        if (data.comicid === comicIdRef.current) {
          if (data.status === "success") {
            navigate(`/series/${comicIdRef.current}`);
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

  const handleAddComic = async (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();

    try {
      comicIdRef.current = comic.comicid ?? comic.id ?? null;
      setIsProcessing(true);

      if (isManga) {
        await addMangaMutation.mutateAsync(comic.comicid ?? comic.id);
      } else {
        await addComicMutation.mutateAsync(comic.comicid ?? comic.id);
      }
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

  if (isAdded) {
    return (
      <Button variant="outline" size="sm" disabled>
        <Check className="w-3 h-3 mr-1" />
        Added
      </Button>
    );
  }

  if (isProcessing) {
    return (
      <Button variant="outline" size="sm" disabled>
        <Loader2 className="w-3 h-3 mr-1 animate-spin" />
        Processing...
      </Button>
    );
  }

  const isPending = isManga
    ? addMangaMutation.isPending
    : addComicMutation.isPending;
  return (
    <Button
      onClick={handleAddComic}
      disabled={isPending}
      variant="outline"
      size="sm"
      className="border-primary text-primary hover:bg-primary hover:text-primary-foreground"
    >
      <Plus className="w-3 h-3 mr-1" />
      {isPending ? "Adding..." : "Add"}
    </Button>
  );
}

// Server-side sort header for search results
function ServerSortHeader({
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

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handleClick();
    }
  };

  return (
    <div
      className="flex items-center gap-1 cursor-pointer select-none hover:text-foreground"
      role="button"
      tabIndex={0}
      aria-sort={ariaSort}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
    >
      <span>{title}</span>
      {sortState === "asc" ? (
        <ChevronUp className="w-4 h-4" />
      ) : sortState === "desc" ? (
        <ChevronDown className="w-4 h-4" />
      ) : (
        <ChevronsUpDown className="w-4 h-4 text-muted-foreground/50" />
      )}
    </div>
  );
}

export default function SearchResultsTable({
  results,
  currentSort,
  onSortChange,
  contentType,
}: SearchResultsTableProps) {
  const isManga = contentType === "manga";
  const issuesLabel = isManga ? "Chapters" : "Issues";
  const publisherLabel = isManga ? "Author" : "Publisher";

  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({
    publisher: true,
    seriesStatus: false,
    contentRating: false,
  });

  const handleToggleColumn = (columnId: string) => {
    setColumnVisibility((prev) => ({
      ...prev,
      [columnId]: prev[columnId] === false,
    }));
  };

  const columns = useMemo(
    () => [
      columnHelper.display({
        id: "cover",
        header: "",
        enableSorting: false,
        enableHiding: false,
        size: 50,
        cell: ({ row }) => <CoverThumbnail comic={row.original} />,
      }),
      columnHelper.accessor("name", {
        id: "series",
        enableHiding: false,
        header: () => (
          <ServerSortHeader
            columnId="series"
            title="Series"
            currentSort={currentSort}
            onSortChange={onSortChange}
          />
        ),
        cell: ({ row }) => {
          const comic = row.original;
          const description = getDescription(comic);
          const sourceLabel =
            SOURCE_LABELS[comic.metadata_source ?? ""] ?? null;

          const nameContent = (
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="font-medium truncate">{comic.name}</span>
                {sourceLabel && (
                  <Badge
                    variant="outline"
                    className="text-[10px] px-1.5 py-0 font-normal shrink-0"
                  >
                    {sourceLabel}
                  </Badge>
                )}
                {comic.url && isSafeUrl(comic.url) && (
                  <a
                    href={comic.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="text-muted-foreground hover:text-foreground shrink-0"
                    aria-label={`Open ${comic.name} on provider site`}
                  >
                    <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>
              {description && (
                <div className="text-xs text-muted-foreground/70 mt-0.5 truncate max-w-[300px]">
                  {truncate(description, 120)}
                </div>
              )}
            </div>
          );

          if (description && description.length > 120) {
            return (
              <HoverCard openDelay={300}>
                <HoverCardTrigger asChild>{nameContent}</HoverCardTrigger>
                <HoverCardContent
                  side="right"
                  align="start"
                  collisionPadding={16}
                  className="w-80 max-h-[50vh] overflow-y-auto text-sm"
                >
                  <p className="font-medium mb-1">{comic.name}</p>
                  <p className="text-muted-foreground leading-relaxed">
                    {description}
                  </p>
                </HoverCardContent>
              </HoverCard>
            );
          }

          return nameContent;
        },
      }),
      columnHelper.accessor("publisher", {
        id: "publisher",
        meta: { label: publisherLabel },
        header: publisherLabel,
        cell: ({ row }) => {
          const pub = row.original.publisher;
          if (!pub || pub === "Unknown") return <span>{"\u2014"}</span>;
          return <span className="text-sm">{pub}</span>;
        },
      }),
      columnHelper.accessor("comicyear", {
        id: "year",
        meta: { label: "Year" },
        header: () => (
          <ServerSortHeader
            columnId="year"
            title="Year"
            currentSort={currentSort}
            onSortChange={onSortChange}
          />
        ),
        cell: ({ getValue }) => <span>{getValue() || "\u2014"}</span>,
      }),
      columnHelper.accessor("issues", {
        id: "issues",
        meta: { label: issuesLabel },
        header: () => (
          <ServerSortHeader
            columnId="issues"
            title={issuesLabel}
            currentSort={currentSort}
            onSortChange={onSortChange}
          />
        ),
        cell: ({ row }) => {
          const issues = row.original.issues ?? row.original.count_of_issues;
          return <span>{issues !== undefined ? issues : "\u2014"}</span>;
        },
      }),
      columnHelper.accessor("status", {
        id: "seriesStatus",
        meta: { label: "Status" },
        header: "Status",
        cell: ({ getValue }) => {
          const status = getValue();
          if (!status) return <span>{"\u2014"}</span>;
          return <span className="text-sm capitalize">{status}</span>;
        },
      }),
      columnHelper.accessor("content_rating", {
        id: "contentRating",
        meta: { label: "Content Rating" },
        header: "Rating",
        cell: ({ getValue }) => {
          const rating = getValue();
          if (!rating) return <span>{"\u2014"}</span>;
          return <span className="text-sm capitalize">{rating}</span>;
        },
      }),
      columnHelper.display({
        id: "inLibrary",
        header: "Library",
        enableSorting: false,
        enableHiding: false,
        cell: ({ row }) =>
          row.original.in_library ? (
            <Badge variant="default">In Library</Badge>
          ) : null,
      }),
      columnHelper.display({
        id: "actions",
        header: "",
        enableSorting: false,
        enableHiding: false,
        cell: ({ row }) => (
          <div className="text-right">
            <ActionCell comic={row.original} contentType={contentType} />
          </div>
        ),
      }),
    ],
    [contentType, issuesLabel, publisherLabel, currentSort, onSortChange],
  );

  const table = useReactTable({
    data: results,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    state: {
      columnVisibility,
    },
    onColumnVisibilityChange: setColumnVisibility,
  });

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <SearchColumnVisibility
          columnVisibility={columnVisibility}
          onToggle={handleToggleColumn}
          isManga={isManga}
        />
      </div>
      <DataTable table={table} />
    </div>
  );
}
