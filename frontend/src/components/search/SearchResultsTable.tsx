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
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useAddComic } from "@/hooks/useSearch";
import { useToast } from "@/components/ui/toast";
import type { SearchResult } from "@/types";

interface SearchResultsTableProps {
  results: SearchResult[];
  currentSort: string;
  onSortChange: (sort: string) => void;
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
  currentSort: string
): "asc" | "desc" | false {
  const mapping = SORT_COLUMN_MAP[columnId];
  if (!mapping) return false;
  if (currentSort === mapping.asc) return "asc";
  if (currentSort === mapping.desc) return "desc";
  return false;
}

// Action cell component to handle add-to-library logic
function ActionCell({ comic }: { comic: SearchResult }) {
  const [isAdded, setIsAdded] = useState(comic.in_library ?? false);
  const [isProcessing, setIsProcessing] = useState(false);
  const addComicMutation = useAddComic();
  const { addToast } = useToast();
  const navigate = useNavigate();
  const comicIdRef = useRef<string | null>(null);

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
      comicIdRef.current = comic.comicid ?? null;
      setIsProcessing(true);

      await addComicMutation.mutateAsync(comic.comicid ?? comic.id);
      setIsAdded(true);
      addToast({
        type: "success",
        title: "Adding Comic...",
        description: `${comic.name} is being added to your library. Please wait...`,
        duration: 5000,
      });
    } catch (err) {
      setIsProcessing(false);
      setIsAdded(false);
      comicIdRef.current = null;
      addToast({
        type: "error",
        title: "Failed to Add Comic",
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
  return (
    <Button
      onClick={handleAddComic}
      disabled={addComicMutation.isPending}
      variant="outline"
      size="sm"
      className="border-primary text-primary hover:bg-primary hover:text-primary-foreground"
    >
      <Plus className="w-3 h-3 mr-1" />
      {addComicMutation.isPending ? "Adding..." : "Add"}
    </Button>
  );
}

export default function SearchResultsTable({
  results,
  currentSort,
  onSortChange,
}: SearchResultsTableProps) {
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

  const columns = useMemo<ColumnDef<SearchResult>[]>(
    () => [
      {
        id: "series",
        accessorKey: "name",
        header: "Series",
        cell: ({ row }: CellContext<SearchResult, unknown>) => (
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
      {
        id: "year",
        accessorKey: "comicyear",
        header: "Year",
        cell: ({ getValue }: CellContext<SearchResult, unknown>) => (
          <span>{(getValue() as string) || "—"}</span>
        ),
      },
      {
        id: "issues",
        accessorKey: "issues",
        header: "Issues",
        cell: ({ row }: CellContext<SearchResult, unknown>) => {
          const issues = row.original.issues ?? row.original.count_of_issues;
          return <span>{issues !== undefined ? issues : "—"}</span>;
        },
      },
      {
        id: "status",
        header: "Status",
        enableSorting: false,
        cell: ({ row }: CellContext<SearchResult, unknown>) =>
          row.original.in_library ? (
            <Badge variant="secondary">In Library</Badge>
          ) : null,
      },
      {
        id: "actions",
        header: "",
        enableSorting: false,
        cell: ({ row }: CellContext<SearchResult, unknown>) => (
          <div className="text-right">
            <ActionCell comic={row.original} />
          </div>
        ),
      },
    ],
    []
  );

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
                              header.getContext()
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
