import { useRef, useState } from "react";
import type { Table as TanstackTable } from "@tanstack/react-table";
import { FileText } from "lucide-react";
import { Input } from "@/components/ui/input";
import { TooltipProvider } from "@/components/ui/tooltip";
import EmptyState from "@/components/ui/EmptyState";
import ConfidenceBadge from "./ConfidenceBadge";
import { DataTable } from "@/components/data-table/DataTable";
import { DataTableServerPagination } from "@/components/data-table/DataTableServerPagination";
import { TableCell, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { getImportIssueLabel } from "@/lib/importUtils";
import type { ImportGroup, ImportFile, PaginationMeta } from "@/types";

interface ImportTableProps {
  /**
   * Built by `ImportPage` with `useTableState` (#396). The page owns the table
   * instance because it owns selection — `ImportBulkActions` is its sibling —
   * and this component only renders it.
   */
  table: TanstackTable<ImportGroup>;
  pagination?: PaginationMeta;
  onNextPage?: () => void;
  onPrevPage?: () => void;
  onIssueNumberChange?: (
    file: ImportFile,
    issueNumber: string,
  ) => Promise<void>;
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
  table,
  pagination,
  onNextPage,
  onPrevPage,
  onIssueNumberChange,
  isMetadataSaving = false,
}: ImportTableProps) {
  if (table.getCoreRowModel().rows.length === 0) {
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
