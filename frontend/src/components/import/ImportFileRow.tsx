import { useRef, useState } from "react";
import { FileText } from "lucide-react";
import { Input } from "@/components/ui/input";
import ConfidenceBadge from "./ConfidenceBadge";
import { cn } from "@/lib/utils";
import type { ImportFile } from "@/types";

type SaveState = "idle" | "dirty" | "saving" | "saved" | "error" | "required";

function FileSaveState({ state }: { state: SaveState }) {
  if (state === "saving") {
    return <span className="text-muted-foreground">Saving...</span>;
  }
  if (state === "saved") {
    return <span className="text-[var(--status-active)]">Saved</span>;
  }
  if (state === "error") {
    return <span className="text-destructive">Save failed</span>;
  }
  if (state === "required") {
    return <span className="text-destructive">Required</span>;
  }
  return null;
}

/** One file of a review group with its issue or chapter number editable in place. */
export default function ImportFileRow({
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
    <div className="grid grid-cols-1 gap-2 border-t border-border bg-muted/20 px-4 py-3 text-sm sm:grid-cols-[minmax(0,1fr)_minmax(8rem,10rem)_minmax(5rem,7rem)] sm:items-center md:px-6">
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
            "h-8 w-full border-border bg-background/80 px-2 py-0 font-mono text-xs focus-visible:ring-primary",
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
        <span className="text-xs bg-surface-3 text-muted-foreground px-2 py-0.5 rounded sm:col-span-3 md:ml-8 w-fit">
          Ignored
        </span>
      )}
    </div>
  );
}
