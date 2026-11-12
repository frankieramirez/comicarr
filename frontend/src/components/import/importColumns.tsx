import { useMemo } from "react";
import { createColumnHelper } from "@tanstack/react-table";
import { Checkbox } from "@/components/ui/checkbox";
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
export function folderOf(group: ImportGroup): string | null {
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
/** "BLAME! (2016)" splits into a name and a year; names without one pass through. */
export function splitSeriesYear(name: string): [string, string | null] {
  const match = name.match(/^(.*?)\s*\((\d{4})\)\s*$/);
  return match ? [match[1], match[2]] : [name, null];
}

/**
 * Columns for the review queue. The table instance itself lives in
 * `ImportPage`, which owns selection because it renders `ImportBulkActions` as
 * a sibling; the columns live here so the page and the selection tests drive
 * the same select column (#396, same shape as #395). Per-group actions live
 * in the pick panel a row opens.
 */
export function useImportColumns() {
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
        columnHelper.accessor("ComicName", {
          header: "Files",
          cell: ({ row }) => {
            const group = row.original;
            const count = group.FileCount ?? group.files.length;
            const folder = folderOf(group);
            return (
              <div className="min-w-0 py-1">
                <div className="truncate text-sm text-foreground">
                  {group.ComicName}
                  {group.Volume ? ` v${group.Volume}` : ""}
                  {group.ComicYear ? ` (${group.ComicYear})` : ""}
                </div>
                <div
                  className="mono-meta truncate"
                  title={getImportGroupTypeLabel(group)}
                >
                  {count} file{count === 1 ? "" : "s"}
                  {folder ? ` · ${folder}` : ""}
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
            const [name, year] = splitSeriesYear(suggestedName);
            return (
              <span className="truncate text-sm text-foreground-2">
                {name}
                {year && (
                  <span className="ml-1.5 font-mono text-xs text-muted-foreground">
                    {year}
                  </span>
                )}
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
              return (
                <span
                  className="inline-flex items-center gap-2"
                  title="No suggestion"
                >
                  <span
                    aria-hidden="true"
                    className="h-1 w-10 rounded-full bg-surface-3"
                  />
                  <span className="mono-meta">–</span>
                  <span className="sr-only">No suggestion</span>
                </span>
              );
            }

            return <ConfidenceBadge confidence={getValue() ?? null} />;
          },
          size: 110,
          enableSorting: false,
        }),
      ]),
    [],
  );
}
