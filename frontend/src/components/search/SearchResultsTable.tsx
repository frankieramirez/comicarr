import { useState, useEffect, useRef, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  useReactTable,
  getCoreRowModel,
  createColumnHelper,
} from "@tanstack/react-table";
import {
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
  Plus,
  Check,
  Loader2,
  ImageOff,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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

  const columns = useMemo(
    () => [
      columnHelper.display({
        id: "cover",
        header: "",
        enableSorting: false,
        size: 50,
        cell: ({ row }) => <CoverThumbnail comic={row.original} />,
      }),
      columnHelper.accessor("name", {
        id: "series",
        header: () => (
          <ServerSortHeader
            columnId="series"
            title="Series"
            currentSort={currentSort}
            onSortChange={onSortChange}
          />
        ),
        cell: ({ row }) => (
          <div>
            <div className="font-medium">{row.original.name}</div>
            {row.original.comicyear && (
              <div className="text-sm text-muted-foreground">
                {row.original.comicyear}
              </div>
            )}
          </div>
        ),
      }),
      columnHelper.accessor("comicyear", {
        id: "year",
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
      columnHelper.display({
        id: "status",
        header: "Status",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.in_library ? (
            <Badge variant="default">In Library</Badge>
          ) : null,
      }),
      columnHelper.display({
        id: "actions",
        header: "",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="text-right">
            <ActionCell comic={row.original} contentType={contentType} />
          </div>
        ),
      }),
    ],
    [contentType, issuesLabel, currentSort, onSortChange],
  );

  const table = useReactTable({
    data: results,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
  });

  return <DataTable table={table} />;
}
