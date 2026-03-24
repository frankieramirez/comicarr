import { useState, useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getExpandedRowModel,
  createColumnHelper,
  type RowSelectionState,
  type ExpandedState,
  type Updater,
} from "@tanstack/react-table";
import { ChevronRight, ChevronDown, FileText, Link2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import StatusBadge from "@/components/StatusBadge";
import EmptyState from "@/components/ui/EmptyState";
import ConfidenceBadge from "./ConfidenceBadge";
import { DataTable } from "@/components/data-table/DataTable";
import { DataTableServerPagination } from "@/components/data-table/DataTableServerPagination";
import { TableCell, TableRow } from "@/components/ui/table";
import type { ImportGroup, ImportFile, PaginationMeta } from "@/types";

const columnHelper = createColumnHelper<ImportGroup>();

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

  const columns = useMemo(
    () => [
      columnHelper.display({
        id: "select",
        header: ({ table }) => (
          <Checkbox
            checked={
              table.getIsAllRowsSelected() ||
              (table.getIsSomeRowsSelected() && "indeterminate")
            }
            onCheckedChange={(value) => table.toggleAllRowsSelected(!!value)}
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            checked={row.getIsSelected()}
            onCheckedChange={(value) => row.toggleSelected(!!value)}
            onClick={(e) => e.stopPropagation()}
          />
        ),
        size: 40,
      }),
      columnHelper.display({
        id: "expander",
        header: "",
        cell: ({ row }) => {
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
      }),
      columnHelper.accessor("ComicName", {
        header: "Series",
        cell: ({ row }) => (
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
        enableSorting: false,
      }),
      columnHelper.accessor("FileCount", {
        header: "Files",
        cell: ({ getValue }) => (
          <span className="font-mono text-sm">{getValue()}</span>
        ),
        enableSorting: false,
      }),
      columnHelper.accessor("MatchConfidence", {
        header: "Confidence",
        cell: ({ getValue }) => (
          <ConfidenceBadge confidence={getValue() ?? null} />
        ),
        enableSorting: false,
      }),
      columnHelper.accessor("SuggestedComicName", {
        header: "Suggested Match",
        cell: ({ row }) => {
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
        enableSorting: false,
      }),
      columnHelper.accessor("Status", {
        header: "Status",
        cell: ({ getValue }) => <StatusBadge status={getValue()} />,
        enableSorting: false,
      }),
      columnHelper.display({
        id: "actions",
        header: "Actions",
        cell: ({ row }) => (
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
      }),
    ],
    [onMatchClick],
  );

  const table = useReactTable({
    data: imports,
    columns,
    state: { rowSelection, expanded },
    onRowSelectionChange: (updater: Updater<RowSelectionState>) => {
      setRowSelection(updater);
      if (onSelectionChange) {
        const newSelection =
          typeof updater === "function" ? updater(rowSelection) : updater;
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
    getRowCanExpand: (row) =>
      !!(row.original.files && row.original.files.length > 0),
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
    <div>
      <DataTable
        table={table}
        onRowClick={(row) => {
          const tableRow = table
            .getRowModel()
            .rows.find((r) => r.original === row);
          tableRow?.toggleExpanded();
        }}
        renderSubRow={(row, colSpan) =>
          row.original.files ? (
            <TableRow key={`${row.id}-expanded`}>
              <TableCell colSpan={colSpan} className="p-0">
                <div className="bg-muted/20">
                  {row.original.files.map((file) => (
                    <FileRow key={file.impID} file={file} />
                  ))}
                </div>
              </TableCell>
            </TableRow>
          ) : null
        }
      />
      {pagination && onNextPage && onPrevPage && (
        <DataTableServerPagination
          pagination={pagination}
          onNextPage={onNextPage}
          onPrevPage={onPrevPage}
        />
      )}
    </div>
  );
}
