import { useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getExpandedRowModel,
  flexRender,
  ColumnDef,
  RowSelectionState,
  ExpandedState,
  Row,
  CellContext,
  HeaderContext,
  Updater,
} from "@tanstack/react-table";
import { ChevronRight, ChevronDown, FileText, Link2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import StatusBadge from "@/components/StatusBadge";
import EmptyState from "@/components/ui/EmptyState";
import ConfidenceBadge from "./ConfidenceBadge";
import type { ImportGroup, ImportFile, PaginationMeta } from "@/types";

interface ImportTableProps {
  imports?: ImportGroup[];
  pagination?: PaginationMeta;
  onNextPage?: () => void;
  onPrevPage?: () => void;
  onSelectionChange?: (selectedIds: string[]) => void;
  onMatchClick?: (group: ImportGroup) => void;
}

function FileRow({ file }: { file: ImportFile }) {
  return (
    <div className="flex items-center gap-4 py-2 px-6 text-sm bg-muted/30 border-t border-card-border">
      <FileText className="w-4 h-4 text-muted-foreground flex-shrink-0 ml-8" />
      <span
        className="font-mono text-xs truncate flex-1"
        title={file.ComicFilename}
      >
        {file.ComicFilename}
      </span>
      {file.IssueNumber && (
        <span className="text-muted-foreground">#{file.IssueNumber}</span>
      )}
      <ConfidenceBadge confidence={file.MatchConfidence} />
      {file.IgnoreFile === 1 && (
        <span className="text-xs bg-gray-500/20 text-gray-600 dark:text-gray-400 px-2 py-0.5 rounded">
          Ignored
        </span>
      )}
    </div>
  );
}

export default function ImportTable({
  imports = [],
  pagination,
  onNextPage,
  onPrevPage,
  onSelectionChange,
  onMatchClick,
}: ImportTableProps) {
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [expanded, setExpanded] = useState<ExpandedState>({});

  const columns: ColumnDef<ImportGroup>[] = [
    {
      id: "select",
      header: ({ table }: HeaderContext<ImportGroup, unknown>) => (
        <Checkbox
          checked={
            table.getIsAllRowsSelected() ||
            (table.getIsSomeRowsSelected() && "indeterminate")
          }
          onCheckedChange={(value) => table.toggleAllRowsSelected(!!value)}
        />
      ),
      cell: ({ row }: CellContext<ImportGroup, unknown>) => (
        <Checkbox
          checked={row.getIsSelected()}
          onCheckedChange={(value) => row.toggleSelected(!!value)}
          onClick={(e) => e.stopPropagation()}
        />
      ),
      size: 40,
    },
    {
      id: "expander",
      header: "",
      cell: ({ row }: CellContext<ImportGroup, unknown>) => {
        const canExpand = row.original.files && row.original.files.length > 0;
        return canExpand ? (
          <button
            onClick={(e) => {
              e.stopPropagation();
              row.toggleExpanded();
            }}
            className="p-1 hover:bg-muted rounded"
          >
            {row.getIsExpanded() ? (
              <ChevronDown className="w-4 h-4" />
            ) : (
              <ChevronRight className="w-4 h-4" />
            )}
          </button>
        ) : null;
      },
      size: 40,
    },
    {
      accessorKey: "ComicName",
      header: "Series",
      cell: ({ row }: CellContext<ImportGroup, unknown>) => (
        <div>
          <div className="font-medium">{row.original.ComicName}</div>
          {row.original.Volume && (
            <div className="text-sm text-muted-foreground">
              Volume {row.original.Volume}
            </div>
          )}
          {row.original.ComicYear && (
            <div className="text-xs text-muted-foreground">
              ({row.original.ComicYear})
            </div>
          )}
        </div>
      ),
    },
    {
      accessorKey: "FileCount",
      header: "Files",
      cell: ({ getValue }: CellContext<ImportGroup, unknown>) => (
        <span className="font-mono text-sm">{getValue() as number}</span>
      ),
    },
    {
      accessorKey: "MatchConfidence",
      header: "Confidence",
      cell: ({ getValue }: CellContext<ImportGroup, unknown>) => (
        <ConfidenceBadge confidence={getValue() as number | null} />
      ),
    },
    {
      accessorKey: "SuggestedComicName",
      header: "Suggested Match",
      cell: ({ row }: CellContext<ImportGroup, unknown>) => {
        const suggestedName = row.original.SuggestedComicName;
        const suggestedId = row.original.SuggestedComicID;

        if (!suggestedName) {
          return (
            <span className="text-muted-foreground/70">No match found</span>
          );
        }

        return (
          <div className="flex items-center gap-2">
            <Link2 className="w-4 h-4 text-muted-foreground" />
            <span className="text-sm">{suggestedName}</span>
            {suggestedId && (
              <span className="text-xs text-muted-foreground">
                (ID: {suggestedId})
              </span>
            )}
          </div>
        );
      },
    },
    {
      accessorKey: "Status",
      header: "Status",
      cell: ({ getValue }: CellContext<ImportGroup, unknown>) => (
        <StatusBadge status={getValue() as string} />
      ),
    },
    {
      id: "actions",
      header: "Actions",
      cell: ({ row }: CellContext<ImportGroup, unknown>) => (
        <Button
          size="sm"
          variant="outline"
          onClick={(e) => {
            e.stopPropagation();
            onMatchClick?.(row.original);
          }}
        >
          Match
        </Button>
      ),
    },
  ];

  const table = useReactTable({
    data: imports,
    columns,
    state: {
      rowSelection,
      expanded,
    },
    onRowSelectionChange: (updater: Updater<RowSelectionState>) => {
      setRowSelection(updater);
      if (onSelectionChange) {
        const newSelection =
          typeof updater === "function" ? updater(rowSelection) : updater;
        // Get all impIDs from selected groups (all files within each group)
        const selectedIds: string[] = [];
        Object.keys(newSelection).forEach((index) => {
          const group = imports[parseInt(index)];
          if (group?.files) {
            group.files.forEach((file) => selectedIds.push(file.impID));
          }
        });
        onSelectionChange(selectedIds);
      }
    },
    onExpandedChange: setExpanded,
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    getRowId: (row) => `${row.DynamicName}-${row.Volume || "null"}`,
    enableRowSelection: true,
    getRowCanExpand: (row: Row<ImportGroup>) =>
      row.original.files && row.original.files.length > 0,
  });

  if (imports.length === 0) {
    return (
      <EmptyState
        variant="search"
        title="No pending imports"
        description="All files have been imported or there are no files to import."
      />
    );
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
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="bg-card divide-y divide-card-border">
            {table.getRowModel().rows.map((row) => (
              <>
                <tr
                  key={row.id}
                  className="hover:bg-muted/50 cursor-pointer transition-colors"
                  onClick={() => row.toggleExpanded()}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-6 py-4 whitespace-nowrap">
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext(),
                      )}
                    </td>
                  ))}
                </tr>
                {row.getIsExpanded() && row.original.files && (
                  <tr key={`${row.id}-expanded`}>
                    <td colSpan={columns.length} className="p-0">
                      <div className="bg-muted/20">
                        {row.original.files.map((file) => (
                          <FileRow key={file.impID} file={file} />
                        ))}
                      </div>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>
      {pagination && (
        <div className="border-t border-card-border px-6 py-3 flex items-center justify-between bg-muted/50">
          <div className="text-sm text-gray-600">
            Showing {pagination.offset + 1} to{" "}
            {Math.min(pagination.offset + pagination.limit, pagination.total)}{" "}
            of {pagination.total} groups
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
