import { useMemo } from "react";
import { createColumnHelper } from "@tanstack/react-table";
import {
  ChevronRight,
  ChevronDown,
  Link2,
  Eye,
  EyeOff,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import StatusBadge from "@/components/StatusBadge";
import ConfidenceBadge from "./ConfidenceBadge";
import { encodeRowId } from "@/components/data-table/rowId";
import {
  getIsAllSelected,
  toggleAllSelected,
} from "@/components/data-table/useTableState";
import { getImportGroupTypeLabel } from "@/lib/importUtils";
import type { ImportGroup } from "@/types";

const columnHelper = createColumnHelper<ImportGroup>();

/**
 * `queries.py` returns the SQL group-by key as `DynamicName`, so distinct rows
 * are guaranteed distinct `(DynamicName, Volume)` pairs — the encoding is the
 * only part that could collapse them. The previous bare join mapped both
 * `null` and `""` to `"null"`, which SQL groups separately (#383, #396).
 */
export function getImportGroupRowId(row: ImportGroup): string {
  return encodeRowId([row.DynamicName, row.Volume]);
}

/**
 * The bulk-action fan-out: selected *groups* map to their constituent file
 * `impID`s, which row ids alone cannot express — that is why `useTableState`
 * returns `selectedRows` as well as `selectedIds` (#359). Built from the
 * selected row objects, never from raw `rowSelection` keys, so a data refresh
 * recomputes the file ids from the fresh groups.
 */
export function getSelectedImportFileIds(
  selectedGroups: ImportGroup[],
): string[] {
  return selectedGroups.flatMap((group) =>
    group.files.map((file) => file.impID),
  );
}

/**
 * Columns for the pending-imports table. The table instance itself lives in
 * `ImportPage`, which owns selection because it renders `ImportBulkActions` as
 * a sibling; the columns live here so the page and the selection tests drive
 * the same select column (#396, same shape as #395).
 */
export function useImportColumns({
  onMatchClick,
  onIgnoreClick,
  onDeleteClick,
  isActionLoading = false,
}: {
  onMatchClick?: (group: ImportGroup) => void;
  onIgnoreClick?: (group: ImportGroup, ignore: boolean) => void;
  onDeleteClick?: (group: ImportGroup) => void;
  isActionLoading?: boolean;
}) {
  return useMemo(
    () => [
      columnHelper.display({
        id: "select",
        header: ({ table }) => (
          <Checkbox
            checked={getIsAllSelected(table)}
            onCheckedChange={(value) => toggleAllSelected(table, !!value)}
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
          // [].every() is true; require files so empty groups stay "Ignore".
          const files = row.original.files ?? [];
          const allIgnored =
            files.length > 0 && files.every((file) => file.IgnoreFile === 1);
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
}
