import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getExpandedRowModel,
  createColumnHelper,
  type RowSelectionState,
  type ExpandedState,
  type Updater,
} from "@tanstack/react-table";
import {
  ChevronRight,
  ChevronDown,
  FileText,
  Link2,
  Eye,
  EyeOff,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import StatusBadge from "@/components/StatusBadge";
import EmptyState from "@/components/ui/EmptyState";
import ConfidenceBadge from "./ConfidenceBadge";
import { DataTable } from "@/components/data-table/DataTable";
import { DataTableServerPagination } from "@/components/data-table/DataTableServerPagination";
import { TableCell, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import {
  getImportGroupTypeLabel,
  getImportIssueLabel,
} from "@/lib/importUtils";
import type { ImportGroup, ImportFile, PaginationMeta } from "@/types";

const columnHelper = createColumnHelper<ImportGroup>();

function getImportGroupRowId(row: ImportGroup): string {
  return `${row.DynamicName}-${row.Volume || "null"}`;
}

function getSelectedImportIds(
  imports: ImportGroup[],
  selection: RowSelectionState,
): { selectedIds: string[]; selectedGroupIds: string[] } {
  const selectedIds: string[] = [];
  const selectedGroupIds: string[] = [];

  Object.keys(selection).forEach((rowId) => {
    if (!selection[rowId]) {
      return;
    }
    const group = imports.find(
      (importGroup) => getImportGroupRowId(importGroup) === rowId,
    );
    if (group?.files) {
      selectedGroupIds.push(rowId);
      group.files.forEach((file) => selectedIds.push(file.impID));
    }
  });

  return { selectedIds, selectedGroupIds };
}

interface ImportTableProps {
  imports?: ImportGroup[];
  pagination?: PaginationMeta;
  onNextPage?: () => void;
  onPrevPage?: () => void;
  onSelectionChange?: (
    selectedIds: string[],
    selectedGroupIds: string[],
  ) => void;
  onMatchClick?: (group: ImportGroup) => void;
  onIgnoreClick?: (group: ImportGroup, ignore: boolean) => void;
  onDeleteClick?: (group: ImportGroup) => void;
  onIssueNumberChange?: (
    file: ImportFile,
    issueNumber: string,
  ) => Promise<void>;
  isActionLoading?: boolean;
  isMetadataSaving?: boolean;
}

type SaveState = "idle" | "dirty" | "saving" | "saved" | "error" | "required";

function FileSaveState({ state }: { state: SaveState }) {
  if (state === "saving") {
    return <span className="text-muted-foreground">Saving...</span>;
  }
  if (state === "saved") {
    return <span className="text-success">Saved</span>;
  }
  if (state === "error") {
    return <span className="text-destructive">Save failed</span>;
  }
  if (state === "required") {
    return <span className="text-destructive">Required</span>;
  }
  return null;
}

function FileRow({
  file,
  label,
  onIssueNumberChange,
  isMetadataSaving = false,
}: {
  file: ImportFile;
  label: string;
  onIssueNumberChange?: (
    file: ImportFile,
    issueNumber: string,
  ) => Promise<void>;
  isMetadataSaving?: boolean;
}) {
  const [issueNumber, setIssueNumber] = useState(file.IssueNumber ?? "");
  const [savedIssueNumber, setSavedIssueNumber] = useState(
    file.IssueNumber ?? "",
  );
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const skipNextBlurSaveRef = useRef(false);
  const hasMatchMetadata = Boolean(
    file.SuggestedComicName ||
    file.SuggestedComicID ||
    file.MatchConfidence != null,
  );

  const saveIssueNumber = async () => {
    const nextIssueNumber = issueNumber.trim();
    if (nextIssueNumber === savedIssueNumber) {
      setIssueNumber(savedIssueNumber);
      setSaveState("idle");
      return;
    }
    if (!nextIssueNumber) {
      setSaveState("required");
      return;
    }
    try {
      setSaveState("saving");
      await onIssueNumberChange?.(file, nextIssueNumber);
      setSavedIssueNumber(nextIssueNumber);
      setIssueNumber(nextIssueNumber);
      setSaveState("saved");
    } catch {
      setSaveState("error");
    }
  };

  return (
    <div className="grid grid-cols-1 gap-2 border-t border-card-border bg-muted/20 px-4 py-3 text-sm sm:grid-cols-[minmax(0,1fr)_minmax(8rem,10rem)_minmax(5rem,7rem)] sm:items-center md:px-6">
      <div className="flex min-w-0 items-center gap-2 md:pl-8">
        <FileText className="w-4 h-4 text-muted-foreground flex-shrink-0" />
        <span
          className="font-mono text-xs truncate min-w-0"
          title={file.ComicFilename}
        >
          {file.ComicFilename}
        </span>
      </div>

      <label className="grid gap-1 text-xs text-muted-foreground sm:max-w-[10rem]">
        <span className="font-mono uppercase tracking-wider">{label}</span>
        <Input
          aria-label={`${label} for ${file.ComicFilename}`}
          value={issueNumber}
          placeholder="Unknown"
          disabled={
            isMetadataSaving || !onIssueNumberChange || saveState === "saving"
          }
          onChange={(event) => {
            const nextValue = event.target.value;
            setIssueNumber(nextValue);
            setSaveState(
              nextValue.trim() === savedIssueNumber ? "idle" : "dirty",
            );
          }}
          onBlur={() => {
            if (skipNextBlurSaveRef.current) {
              skipNextBlurSaveRef.current = false;
              return;
            }
            void saveIssueNumber();
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              void saveIssueNumber();
            }
            if (event.key === "Escape") {
              skipNextBlurSaveRef.current = true;
              setIssueNumber(savedIssueNumber);
              setSaveState("idle");
              event.currentTarget.blur();
            }
          }}
          className={cn(
            "h-8 w-full border-card-border bg-background/80 px-2 py-0 font-mono text-xs focus-visible:ring-primary",
            saveState === "dirty" && "border-primary/60",
            (saveState === "error" || saveState === "required") &&
              "border-destructive focus-visible:ring-destructive",
          )}
        />
      </label>

      <div className="min-h-5 text-xs sm:text-right">
        <FileSaveState state={saveState} />
      </div>

      {hasMatchMetadata && (
        <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-muted-foreground sm:col-span-3 md:pl-8">
          {file.SuggestedComicName && (
            <span className="truncate">
              Suggested: {file.SuggestedComicName}
            </span>
          )}
          {file.SuggestedComicID && !file.SuggestedComicName && (
            <span className="truncate">
              Suggested ID: {file.SuggestedComicID}
            </span>
          )}
          {file.MatchConfidence != null && (
            <ConfidenceBadge confidence={file.MatchConfidence} />
          )}
        </div>
      )}

      {file.IgnoreFile === 1 && (
        <span className="text-xs bg-gray-500/20 text-gray-600 dark:text-gray-400 px-2 py-0.5 rounded sm:col-span-3 md:ml-8 w-fit">
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
  onIgnoreClick,
  onDeleteClick,
  onIssueNumberChange,
  isActionLoading = false,
  isMetadataSaving = false,
}: ImportTableProps) {
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [expanded, setExpanded] = useState<ExpandedState>({});
  const lastSelectionKeyRef = useRef(JSON.stringify([[], []]));

  const emitSelectionChange = useCallback(
    (selection: RowSelectionState) => {
      if (!onSelectionChange) {
        return;
      }
      const { selectedIds, selectedGroupIds } = getSelectedImportIds(
        imports,
        selection,
      );
      const selectionKey = JSON.stringify([selectedIds, selectedGroupIds]);
      if (lastSelectionKeyRef.current === selectionKey) {
        return;
      }
      lastSelectionKeyRef.current = selectionKey;
      onSelectionChange(selectedIds, selectedGroupIds);
    },
    [imports, onSelectionChange],
  );

  useEffect(() => {
    emitSelectionChange(rowSelection);
  }, [emitSelectionChange, rowSelection]);

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
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  aria-label={
                    row.getIsExpanded()
                      ? "Collapse import files"
                      : "Expand import files"
                  }
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
              </TooltipTrigger>
              <TooltipContent>
                {row.getIsExpanded() ? "Collapse files" : "Review files"}
              </TooltipContent>
            </Tooltip>
          ) : null;
        },
        size: 40,
      }),
      columnHelper.accessor("ComicName", {
        header: "Series",
        cell: ({ row }) => (
          <div>
            <div className="font-medium">{row.original.ComicName}</div>
            <div className="mt-1">
              <span className="inline-flex items-center rounded border border-border/70 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                {getImportGroupTypeLabel(row.original)}
              </span>
            </div>
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
        cell: ({ row, getValue }) => {
          if (
            !row.original.SuggestedComicID &&
            !row.original.SuggestedComicName
          ) {
            return (
              <span className="text-xs text-muted-foreground/70">
                No suggestion
              </span>
            );
          }

          return <ConfidenceBadge confidence={getValue() ?? null} />;
        },
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
        cell: ({ row }) => {
          const allIgnored =
            row.original.files?.every((file) => file.IgnoreFile === 1) ?? false;
          const ignoreLabel = allIgnored ? "Unignore import" : "Ignore import";

          return (
            <div className="flex items-center gap-1">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="sm"
                    variant="outline"
                    aria-label="Match import"
                    disabled={isActionLoading}
                    className="h-8 px-2"
                    onClick={(e) => {
                      e.stopPropagation();
                      onMatchClick?.(row.original);
                    }}
                  >
                    <Link2 className="w-4 h-4" />
                    Match
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Match this review group</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="icon"
                    variant="outline"
                    aria-label={ignoreLabel}
                    disabled={isActionLoading}
                    onClick={(e) => {
                      e.stopPropagation();
                      onIgnoreClick?.(row.original, !allIgnored);
                    }}
                  >
                    {allIgnored ? (
                      <Eye className="w-4 h-4" />
                    ) : (
                      <EyeOff className="w-4 h-4" />
                    )}
                    <span className="sr-only">{ignoreLabel}</span>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{ignoreLabel}</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label="Delete import record"
                    disabled={isActionLoading}
                    className="text-destructive hover:text-destructive"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteClick?.(row.original);
                    }}
                  >
                    <Trash2 className="w-4 h-4" />
                    <span className="sr-only">Delete</span>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Delete import record</TooltipContent>
              </Tooltip>
            </div>
          );
        },
      }),
    ],
    [isActionLoading, onDeleteClick, onIgnoreClick, onMatchClick],
  );

  const table = useReactTable({
    data: imports,
    columns,
    state: { rowSelection, expanded },
    onRowSelectionChange: (updater: Updater<RowSelectionState>) => {
      const newSelection =
        typeof updater === "function" ? updater(rowSelection) : updater;
      setRowSelection(newSelection);
      emitSelectionChange(newSelection);
    },
    onExpandedChange: setExpanded,
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    getRowId: getImportGroupRowId,
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
    <TooltipProvider delayDuration={150}>
      <DataTable
        table={table}
        className="overflow-x-auto"
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
                    <FileRow
                      key={`${file.impID}-${file.IssueNumber ?? ""}`}
                      file={file}
                      label={getImportIssueLabel(row.original)}
                      onIssueNumberChange={onIssueNumberChange}
                      isMetadataSaving={isMetadataSaving}
                    />
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
    </TooltipProvider>
  );
}
