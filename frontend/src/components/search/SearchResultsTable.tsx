import { useState, useEffect, useRef, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  ColumnDef,
  CellContext,
} from "@tanstack/react-table";
import {
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
  Plus,
  Check,
  Loader2,
  ImageOff,
  Book,
  BookOpen,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useAddComic, useAddManga } from "@/hooks/useSearch";
import { useToast } from "@/components/ui/toast";
import type { SearchResult, ContentType } from "@/types";

// Extended search result with content_type for unified search
interface ExtendedSearchResult extends SearchResult {
  content_type?: ContentType;
}

// Lazy-loaded cover thumbnail component
function CoverThumbnail({ comic }: { comic: ExtendedSearchResult }) {
  const [imageError, setImageError] = useState(false);
  const [isLoaded, setIsLoaded] = useState(false);

  // Try different image sources
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
  results: ExtendedSearchResult[];
  currentSort: string;
  onSortChange: (sort: string) => void;
  contentType?: ContentType;
  showTypeColumn?: boolean;
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

// Get current sort state for a column
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

// Type badge component
function TypeBadge({ contentType }: { contentType: ContentType }) {
  if (contentType === "manga") {
    return (
      <Badge variant="secondary" className="text-xs px-1.5 py-0">
        <BookOpen className="w-3 h-3 mr-1" />
        Manga
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="text-xs px-1.5 py-0">
      <Book className="w-3 h-3 mr-1" />
      Comic
    </Badge>
  );
}

// Action cell component to handle add-to-library logic
function ActionCell({ comic, contentType = "comic" }: { comic: ExtendedSearchResult; contentType?: ContentType }) {
  const [isAdded, setIsAdded] = useState(comic.in_library ?? false);
  const [isProcessing, setIsProcessing] = useState(false);
  const addComicMutation = useAddComic();
  const addMangaMutation = useAddManga();
  const { addToast } = useToast();
  const navigate = useNavigate();
  const comicIdRef = useRef<string | null>(null);

  // Use content_type from result if available (for unified search), otherwise use prop
  const effectiveContentType = comic.content_type || contentType;
  const isManga = effectiveContentType === "manga";
  const itemLabel = isManga ? "Manga" : "Comic";

  // Listen for SSE events when a comic is being added
  useEffect(() => {
    if (!isProcessing || !comicIdRef.current) return;

    const handleAddById = (event: CustomEvent<string>) => {
      try {
        const data: AddByIdEventDetail = JSON.parse(event.detail);

        // Check if this event is for our comic
        if (data.comicid === comicIdRef.current) {
          if (data.status === "success") {
            // Navigate to series detail page
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

    // Listen for custom event dispatched by useServerEvents
    window.addEventListener("comic-added", handleAddById as EventListener);

    return () => {
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

  // Already in library - show disabled "Added" button
  if (isAdded) {
    return (
      <Button variant="outline" size="sm" disabled>
        <Check className="w-3 h-3 mr-1" />
        Added
      </Button>
    );
  }

  // Processing state
  if (isProcessing) {
    return (
      <Button variant="outline" size="sm" disabled>
        <Loader2 className="w-3 h-3 mr-1 animate-spin" />
        Processing...
      </Button>
    );
  }

  // Default - Add button with primary outline style
  const isPending = isManga ? addMangaMutation.isPending : addComicMutation.isPending;
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

export default function SearchResultsTable({
  results,
  currentSort,
  onSortChange,
  contentType = "comic",
  showTypeColumn = false,
}: SearchResultsTableProps) {
  const isManga = contentType === "manga";
  const issuesLabel = showTypeColumn ? "Issues/Ch." : isManga ? "Chapters" : "Issues";

  // Handle column header click for sorting
  const handleSortClick = (columnId: string) => {
    const mapping = SORT_COLUMN_MAP[columnId];
    if (!mapping) return;

    const currentState = getColumnSort(columnId, currentSort);
    // Toggle: none -> desc -> asc -> desc (default to desc first for year)
    if (currentState === false) {
      onSortChange(mapping.desc);
    } else if (currentState === "desc") {
      onSortChange(mapping.asc);
    } else {
      onSortChange(mapping.desc);
    }
  };

  const columns = useMemo<ColumnDef<ExtendedSearchResult>[]>(() => {
    const cols: ColumnDef<ExtendedSearchResult>[] = [
      {
        id: "cover",
        header: "",
        enableSorting: false,
        size: 50,
        cell: ({ row }: CellContext<ExtendedSearchResult, unknown>) => (
          <CoverThumbnail comic={row.original} />
        ),
      },
      {
        id: "series",
        accessorKey: "name",
        header: "Series",
        cell: ({ row }: CellContext<ExtendedSearchResult, unknown>) => (
          <div>
            <div className="font-medium">{row.original.name}</div>
            {row.original.comicyear && (
              <div className="text-sm text-muted-foreground">
                {row.original.comicyear}
              </div>
            )}
          </div>
        ),
      },
    ];

    // Add type column when showing unified results
    if (showTypeColumn) {
      cols.push({
        id: "type",
        header: "Type",
        enableSorting: false,
        cell: ({ row }: CellContext<ExtendedSearchResult, unknown>) => (
          <TypeBadge contentType={row.original.content_type || "comic"} />
        ),
      });
    }

    cols.push(
      {
        id: "year",
        accessorKey: "comicyear",
        header: "Year",
        cell: ({ getValue }: CellContext<ExtendedSearchResult, unknown>) => (
          <span>{(getValue() as string) || "—"}</span>
        ),
      },
      {
        id: "issues",
        accessorKey: "issues",
        header: issuesLabel,
        cell: ({ row }: CellContext<ExtendedSearchResult, unknown>) => {
          const issues = row.original.issues ?? row.original.count_of_issues;
          return <span>{issues !== undefined ? issues : "—"}</span>;
        },
      },
      {
        id: "status",
        header: "Status",
        enableSorting: false,
        cell: ({ row }: CellContext<ExtendedSearchResult, unknown>) =>
          row.original.in_library ? (
            <Badge variant="default">In Library</Badge>
          ) : null,
      },
      {
        id: "actions",
        header: "",
        enableSorting: false,
        cell: ({ row }: CellContext<ExtendedSearchResult, unknown>) => (
          <div className="text-right">
            <ActionCell
              comic={row.original}
              contentType={row.original.content_type || contentType}
            />
          </div>
        ),
      },
    );

    return cols;
  }, [contentType, issuesLabel, showTypeColumn]);

  const table = useReactTable({
    data: results,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true, // Server-side sorting
  });

  return (
    <div className="rounded-lg border border-card-border bg-card card-shadow overflow-hidden">
      <div className="overflow-x-auto custom-scrollbar">
        <table className="w-full">
          <thead className="bg-muted/50 border-b border-card-border">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const isSortable = !!SORT_COLUMN_MAP[header.id];
                  const sortState = isSortable
                    ? getColumnSort(header.id, currentSort)
                    : false;

                  return (
                    <th
                      key={header.id}
                      className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider"
                    >
                      {header.isPlaceholder ? null : (
                        <div
                          className={
                            isSortable
                              ? "flex items-center gap-1 cursor-pointer select-none hover:text-foreground"
                              : ""
                          }
                          onClick={
                            isSortable
                              ? () => handleSortClick(header.id)
                              : undefined
                          }
                        >
                          <span>
                            {flexRender(
                              header.column.columnDef.header,
                              header.getContext(),
                            )}
                          </span>
                          {isSortable && (
                            <span>
                              {sortState === "asc" ? (
                                <ChevronUp className="w-4 h-4" />
                              ) : sortState === "desc" ? (
                                <ChevronDown className="w-4 h-4" />
                              ) : (
                                <ChevronsUpDown className="w-4 h-4" />
                              )}
                            </span>
                          )}
                        </div>
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-card-border">
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="hover:bg-accent/50 transition-colors">
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-6 py-4 whitespace-nowrap">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
