import { ph, plural, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
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

/** "Reconciled 3 existing manga series." / "3 existing comic series reconciled". */
function reconciledLine(
  type: "comic" | "manga",
  count: number,
  sentence: boolean,
): string {
  if (type === "manga") {
    return sentence
      ? plural(count, {
          one: "Reconciled # existing manga series.",
          other: "Reconciled # existing manga series.",
        })
      : plural(count, {
          one: "# existing manga series reconciled",
          other: "# existing manga series reconciled",
        });
  }
  return sentence
    ? plural(count, {
        one: "Reconciled # existing comic series.",
        other: "Reconciled # existing comic series.",
      })
    : plural(count, {
        one: "# existing comic series reconciled",
        other: "# existing comic series reconciled",
      });
}

export default function LibraryScanResults({
  results,
  scanId,
  onConfirm,
  isConfirming,
  type,
}: LibraryScanResultsProps) {
  const matchedResults = results.filter(
    (r) => r.matched && r.match?.comicid && !r.already_in_library,
  );
  const reconciledResults = results.filter((r) => r.reconciled);
  const [selectedIds, setSelectedIds] = useState<string[]>(
    matchedResults.map((r) => r.match!.comicid),
  );

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Reset selection when server scan results change
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

  const importableResults = results
    .filter((r) => !r.already_in_library)
    .sort((left, right) => {
      const leftIsMatched = Boolean(left.matched && left.match?.comicid);
      const rightIsMatched = Boolean(right.matched && right.match?.comicid);

      if (leftIsMatched !== rightIsMatched) {
        return leftIsMatched ? -1 : 1;
      }

      return left.series_name.localeCompare(right.series_name, undefined, {
        numeric: true,
        sensitivity: "base",
      });
    });

  if (importableResults.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-muted/50 p-6 text-center text-muted-foreground">
        <Trans>
          No new series found in directory. All series are already in your
          library.
        </Trans>
        {reconciledResults.length > 0 && (
          <span className="block mt-1 text-foreground">
            {reconciledLine(type, reconciledResults.length, true)}
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="text-sm text-muted-foreground">
          {t`${ph({ matched: matchedResults.length })} matched of ${ph({ found: importableResults.length })} series found`}
          {reconciledResults.length > 0 && (
            <span className="ms-2">
              {reconciledLine(type, reconciledResults.length, false)}
            </span>
          )}
          {selectedIds.length > 0 && (
            <span className="ms-2 font-medium text-foreground">
              {t`(${ph({ count: selectedIds.length })} selected)`}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={selectAll}>
            <Trans>Select All</Trans>
          </Button>
          <Button variant="ghost" size="sm" onClick={deselectAll}>
            <Trans>Deselect All</Trans>
          </Button>
          <Button
            size="sm"
            onClick={() => onConfirm(scanId, selectedIds)}
            disabled={selectedIds.length === 0 || isConfirming}
          >
            <Check className="w-4 h-4 me-1" />
            {t`Import Selected (${ph({ count: selectedIds.length })})`}
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
                aria-label={t`Select ${ph({ series_name: result.series_name })}`}
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
                    {plural(result.file_count, {
                      one: "(# file)",
                      other: "(# files)",
                    })}
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
                <span className="text-xs text-muted-foreground">
                  <Trans>No match</Trans>
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
