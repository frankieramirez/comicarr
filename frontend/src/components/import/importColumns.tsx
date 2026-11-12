import { useMemo } from "react";
import { createColumnHelper } from "@tanstack/react-table";
import { ChevronRight, ChevronDown, Eye, EyeOff, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import ConfidenceBadge from "./ConfidenceBadge";
import { encodeRowId } from "@/components/data-table/rowId";
import {
  type ComicarrTableFeatures,
  getIsAllSelected,
  toggleAllSelected,
} from "@/components/data-table/useTableState";
import { getImportGroupTypeLabel } from "@/lib/importUtils";
import type { ImportGroup } from "@/types";

const columnHelper = createColumnHelper<ComicarrTableFeatures, ImportGroup>();

/** The folder the group's files sit in, trimmed to its last two segments. */
function folderOf(group: ImportGroup): string | null {
  const location = group.files[0]?.ComicLocation;
  if (!location) return null;
  const parts = location.split(/[\\/]/).filter(Boolean);
  parts.pop();
  return parts.length ? `${parts.slice(-2).join("/")}/` : null;
}

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
  onMatchClick?: (group: ImportGroup, trigger: HTMLElement) => void;
  onIgnoreClick?: (group: ImportGroup, ignore: boolean) => void;
  onDeleteClick?: (group: ImportGroup) => void;
  isActionLoading?: boolean;
}) {
  return useMemo(
    () =>
      columnHelper.columns([
        columnHelper.display({
          id: "select",
          header: ({ table }) => (
            <Checkbox
              aria-label="Select all rows"
              checked={getIsAllSelected(table)}
              onCheckedChange={(value) => toggleAllSelected(table, !!value)}
            />
          ),
          cell: ({ row }) => (
            <Checkbox
              aria-label={`Select ${row.original.ComicName || row.original.DynamicName}`}
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
            const canExpand =
              row.original.files && row.original.files.length > 0;
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
          header: "Files",
          cell: ({ row }) => {
            const group = row.original;
            const count = group.FileCount ?? group.files.length;
            const folder = folderOf(group);
            return (
              <div className="min-w-0">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate text-sm font-medium text-foreground">
                    {group.ComicName}
                    {group.Volume ? ` v${group.Volume}` : ""}
                    {group.ComicYear ? ` (${group.ComicYear})` : ""}
                  </span>
                </div>
                <div className="mono-meta truncate">
                  {count} file{count === 1 ? "" : "s"}
                  {folder ? ` · ${folder}` : ""} ·{" "}
                  <span>{getImportGroupTypeLabel(group)}</span>
                </div>
              </div>
            );
          },
          enableSorting: false,
        }),
        columnHelper.accessor("SuggestedComicName", {
          header: "Best guess",
          cell: ({ row }) => {
            const suggestedName = row.original.SuggestedComicName;
            if (!suggestedName) {
              return (
                <span className="text-sm text-muted-foreground">No match</span>
              );
            }
            return (
              <span
                className="text-sm text-foreground-2"
                title={
                  row.original.SuggestedComicID
                    ? `ID ${row.original.SuggestedComicID}`
                    : undefined
                }
              >
                {suggestedName}
              </span>
            );
          },
          enableSorting: false,
        }),
        columnHelper.accessor("MatchConfidence", {
          header: "Match",
          cell: ({ row, getValue }) => {
            if (
              !row.original.SuggestedComicID &&
              !row.original.SuggestedComicName
            ) {
              return <span className="mono-meta">No suggestion</span>;
            }

            return <ConfidenceBadge confidence={getValue() ?? null} />;
          },
          enableSorting: false,
        }),
        columnHelper.accessor("Status", {
          header: "Status",
          cell: ({ getValue }) => (
            <span className="text-[13px] text-foreground-2">{getValue()}</span>
          ),
          enableSorting: false,
        }),
        columnHelper.display({
          id: "actions",
          header: () => <span className="sr-only">Actions</span>,
          cell: ({ row }) => {
            const files = row.original.files ?? [];
            const allIgnored =
              files.length > 0 && files.every((file) => file.IgnoreFile === 1);
            const ignoreLabel = allIgnored
              ? "Unignore import"
              : "Ignore import";

            return (
              <div className="flex items-center justify-end gap-0.5 opacity-70 transition-opacity group-hover/row:opacity-100 focus-within:opacity-100">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      size="compact"
                      variant="outline"
                      aria-label="Match import"
                      data-import-match={getImportGroupRowId(row.original)}
                      disabled={isActionLoading}
                      onClick={(e) => {
                        e.stopPropagation();
                        onMatchClick?.(row.original, e.currentTarget);
                      }}
                    >
                      Match
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Match this review group</TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      aria-label={ignoreLabel}
                      disabled={isActionLoading}
                      onClick={(e) => {
                        e.stopPropagation();
                        onIgnoreClick?.(row.original, !allIgnored);
                      }}
                    >
                      {allIgnored ? <Eye /> : <EyeOff />}
                      <span className="sr-only">{ignoreLabel}</span>
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{ignoreLabel}</TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      aria-label="Delete import record"
                      disabled={isActionLoading}
                      className="text-muted-foreground hover:text-destructive"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteClick?.(row.original);
                      }}
                    >
                      <Trash2 />
                      <span className="sr-only">Delete</span>
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Delete import record</TooltipContent>
                </Tooltip>
              </div>
            );
          },
        }),
      ]),
    [isActionLoading, onDeleteClick, onIgnoreClick, onMatchClick],
  );
}
