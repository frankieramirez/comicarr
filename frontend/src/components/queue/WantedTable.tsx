import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  ColumnDef,
  SortingState,
  RowSelectionState,
  CellContext,
  HeaderContext,
  Updater,
} from "@tanstack/react-table";
import { X, ChevronUp, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import StatusBadge from "@/components/StatusBadge";
import EmptyState from "@/components/ui/EmptyState";
import { useUnqueueIssue } from "@/hooks/useSeries";
import { useAuth } from "@/contexts/AuthContext";
import type { WantedIssue, PaginationMeta } from "@/types";

function CoverCell({
  comicId,
  apiKey,
}: {
  comicId: string | undefined;
  apiKey: string | null;
}) {
  const [imageError, setImageError] = useState(false);

  return (
    <div className="w-12 h-16 bg-gray-200 rounded overflow-hidden flex-shrink-0">
      {!imageError && comicId && apiKey ? (
        <img
          src={`/api?apikey=${apiKey}&cmd=getComic&id=${comicId}`}
          alt=""
          className="w-full h-full object-cover"
          onError={() => setImageError(true)}
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-muted-foreground/70 text-xs">
          N/A
        </div>
      )}
    </div>
  );
}

interface WantedTableProps {
  issues?: WantedIssue[];
  pagination?: PaginationMeta;
  onNextPage?: () => void;
  onPrevPage?: () => void;
  onSelectionChange?: (selectedIds: string[]) => void;
}

export default function WantedTable({
  issues = [],
  pagination,
  onNextPage,
  onPrevPage,
  onSelectionChange,
}: WantedTableProps) {
  const navigate = useNavigate();
  const { apiKey } = useAuth();
  const [sorting, setSorting] = useState<SortingState>([
    { id: "DateAdded", desc: true },
  ]);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const unqueueIssueMutation = useUnqueueIssue();

  const handleUnqueueIssue = (e: React.MouseEvent, issueId: string) => {
    e.stopPropagation();
    unqueueIssueMutation.mutate(issueId);
  };

  const handleRowClick = (comicId: string) => {
    navigate(`/series/${comicId}`);
  };

  const columns: ColumnDef<WantedIssue>[] = [
    {
      id: "select",
      header: ({ table }: HeaderContext<WantedIssue, unknown>) => (
        <Checkbox
          checked={
            table.getIsAllRowsSelected() ||
            (table.getIsSomeRowsSelected() && "indeterminate")
          }
          onCheckedChange={(value) => table.toggleAllRowsSelected(!!value)}
        />
      ),
      cell: ({ row }: CellContext<WantedIssue, unknown>) => (
        <Checkbox
          checked={row.getIsSelected()}
          onCheckedChange={(value) => row.toggleSelected(!!value)}
          onClick={(e) => e.stopPropagation()}
        />
      ),
      size: 40,
    },
    {
      accessorKey: "cover",
      header: "",
      cell: ({ row }: CellContext<WantedIssue, unknown>) => (
        <CoverCell comicId={row.original.ComicID} apiKey={apiKey} />
      ),
      size: 60,
    },
    {
      accessorKey: "ComicName",
      header: "Series",
      cell: ({ row }: CellContext<WantedIssue, unknown>) => (
        <div>
          <div className="font-medium">{row.original.ComicName}</div>
          {row.original.ComicYear && (
            <div className="text-sm text-muted-foreground">
              ({row.original.ComicYear})
            </div>
          )}
        </div>
      ),
    },
    {
      accessorKey: "Issue_Number",
      header: "#",
      cell: ({ getValue }: CellContext<WantedIssue, unknown>) => (
        <span className="font-mono text-sm">
          {(getValue() as string) || "N/A"}
        </span>
      ),
    },
    {
      accessorKey: "IssueName",
      header: "Issue Name",
      cell: ({ getValue }: CellContext<WantedIssue, unknown>) => {
        const name = getValue() as string | undefined;
        return name ? (
          <span className="text-sm text-foreground">{name}</span>
        ) : (
          <span className="text-sm text-muted-foreground/70">N/A</span>
        );
      },
    },
    {
      accessorKey: "DateAdded",
      header: "Date Added",
      cell: ({ getValue }: CellContext<WantedIssue, unknown>) => {
        const date = getValue() as string | undefined;
        if (!date) return <span className="text-muted-foreground/70">N/A</span>;
        return <span className="text-sm">{date}</span>;
      },
    },
    {
      accessorKey: "IssueDate",
      header: "Release Date",
      cell: ({ getValue }: CellContext<WantedIssue, unknown>) => {
        const date = getValue() as string | undefined;
        if (!date) return <span className="text-muted-foreground/70">N/A</span>;
        return <span className="text-sm">{date}</span>;
      },
    },
    {
      accessorKey: "Status",
      header: "Status",
      cell: ({ getValue }: CellContext<WantedIssue, unknown>) => (
        <StatusBadge status={getValue() as string} />
      ),
    },
    {
      id: "actions",
      header: "Actions",
      cell: ({ row }: CellContext<WantedIssue, unknown>) => {
        const issueId = row.original.IssueID;

        return (
          <div className="flex items-center space-x-2">
            <Button
              size="sm"
              variant="outline"
              onClick={(e) => handleUnqueueIssue(e, issueId)}
              disabled={unqueueIssueMutation.isPending}
              className="text-xs"
            >
              <X className="w-3 h-3 mr-1" />
              Skip
            </Button>
          </div>
        );
      },
    },
  ];

  const table = useReactTable({
    data: issues,
    columns,
    state: {
      sorting,
      rowSelection,
    },
    onSortingChange: setSorting,
    onRowSelectionChange: (updater: Updater<RowSelectionState>) => {
      setRowSelection(updater);
      // Notify parent of selection changes
      if (onSelectionChange) {
        const newSelection =
          typeof updater === "function" ? updater(rowSelection) : updater;
        const selectedIds = Object.keys(newSelection)
          .map((index) => issues[parseInt(index)]?.IssueID)
          .filter(Boolean) as string[];
        onSelectionChange(selectedIds);
      }
    },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (row) => row.IssueID,
    enableRowSelection: true,
  });

  if (issues.length === 0) {
    return <EmptyState variant="wanted" />;
  }

  return (
    <div className="rounded-lg border-card-border bg-card card-shadow overflow-hidden">
      <div className="overflow-x-auto custom-scrollbar">
        <table className="w-full">
          <thead className="bg-muted/50 border-card-border backdrop-blur-sm border-b">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider"
                  >
                    {header.isPlaceholder ? null : (
                      <div
                        className={
                          header.column.getCanSort()
                            ? "flex items-center space-x-1 cursor-pointer select-none hover:text-foreground"
                            : ""
                        }
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        <span>
                          {flexRender(
                            header.column.columnDef.header,
                            header.getContext(),
                          )}
                        </span>
                        {header.column.getCanSort() &&
                          header.column.getIsSorted() && (
                            <span className="text-muted-foreground/70">
                              {header.column.getIsSorted() === "asc" ? (
                                <ChevronUp className="w-4 h-4" />
                              ) : (
                                <ChevronDown className="w-4 h-4" />
                              )}
                            </span>
                          )}
                      </div>
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="bg-card divide-y divide-card-border">
            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                onClick={() => handleRowClick(row.original.ComicID)}
                className="hover:bg-muted/50 cursor-pointer transition-colors"
              >
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
      {pagination && (
        <div className="border-t border-card-border px-6 py-3 flex items-center justify-between bg-muted/50">
          <div className="text-sm text-gray-600">
            Showing {pagination.offset + 1} to{" "}
            {Math.min(pagination.offset + pagination.limit, pagination.total)}{" "}
            of {pagination.total} issues
          </div>
          <div className="flex items-center space-x-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onPrevPage}
              disabled={pagination.offset === 0}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={onNextPage}
              disabled={!pagination.has_more}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
