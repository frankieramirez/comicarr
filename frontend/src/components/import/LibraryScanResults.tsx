import { useState, useEffect } from "react";
import { Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import ConfidenceBadge from "@/components/import/ConfidenceBadge";
import type { ScanResult } from "@/types";

interface LibraryScanResultsProps {
  results: ScanResult[];
  scanId: string;
  onConfirm: (scanId: string, selectedIds: string[]) => void;
  isConfirming: boolean;
  type: "comic" | "manga";
}

export default function LibraryScanResults({
  results,
  scanId,
  onConfirm,
  isConfirming,
  type,
}: LibraryScanResultsProps) {
  // Pre-select all matched series
  const matchedResults = results.filter(
    (r) => r.matched && r.match?.comicid && !r.already_in_library,
  );
  const [selectedIds, setSelectedIds] = useState<string[]>(
    matchedResults.map((r) => r.match!.comicid),
  );

  useEffect(() => {
    setSelectedIds(matchedResults.map((r) => r.match!.comicid));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results]);

  const toggleSelection = (comicId: string) => {
    setSelectedIds((prev) =>
      prev.includes(comicId)
        ? prev.filter((id) => id !== comicId)
        : [...prev, comicId],
    );
  };

  const selectAll = () => {
    setSelectedIds(matchedResults.map((r) => r.match!.comicid));
  };

  const deselectAll = () => {
    setSelectedIds([]);
  };

  const importableResults = results.filter((r) => !r.already_in_library);

  if (importableResults.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-muted/50 p-6 text-center text-muted-foreground">
        No new series found in directory. All series are already in your
        library.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="text-sm text-muted-foreground">
          {matchedResults.length} matched of {importableResults.length} series
          found
          {selectedIds.length > 0 && (
            <span className="ml-2 font-medium text-foreground">
              ({selectedIds.length} selected)
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={selectAll}>
            Select All
          </Button>
          <Button variant="ghost" size="sm" onClick={deselectAll}>
            Deselect All
          </Button>
          <Button
            size="sm"
            onClick={() => onConfirm(scanId, selectedIds)}
            disabled={selectedIds.length === 0 || isConfirming}
          >
            <Check className="w-4 h-4 mr-1" />
            Import Selected ({selectedIds.length})
          </Button>
        </div>
      </div>

      <div className="divide-y divide-border">
        {importableResults.map((result) => {
          const comicId = result.match?.comicid;
          const isSelected = comicId ? selectedIds.includes(comicId) : false;
          const isSelectable = result.matched && !!comicId;

          return (
            <div
              key={result.series_name}
              className={`flex items-center gap-3 px-4 py-3 ${
                isSelectable ? "hover:bg-muted/50 cursor-pointer" : "opacity-60"
              }`}
              onClick={() =>
                isSelectable && comicId && toggleSelection(comicId)
              }
            >
              <Checkbox
                checked={isSelected}
                disabled={!isSelectable}
                onChange={() =>
                  isSelectable && comicId && toggleSelection(comicId)
                }
              />

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium truncate">
                    {result.series_name}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    ({result.file_count} file
                    {result.file_count !== 1 ? "s" : ""})
                  </span>
                </div>
                {result.match && (
                  <div className="text-sm text-muted-foreground flex items-center gap-2 mt-0.5">
                    <span className="truncate">
                      {result.match.name}
                      {result.match.year && ` (${result.match.year})`}
                    </span>
                    {type === "comic" && result.match.publisher && (
                      <span className="text-xs">{result.match.publisher}</span>
                    )}
                    {type === "manga" && result.match.source && (
                      <span className="text-xs uppercase">
                        {result.match.source}
                      </span>
                    )}
                  </div>
                )}
                {result.error && (
                  <div className="text-sm text-destructive flex items-center gap-1 mt-0.5">
                    <X className="w-3 h-3" />
                    {result.error}
                  </div>
                )}
              </div>

              {result.match ? (
                <ConfidenceBadge confidence={result.match.confidence} />
              ) : (
                <span className="text-xs text-muted-foreground">No match</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
