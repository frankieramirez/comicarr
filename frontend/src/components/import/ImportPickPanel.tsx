import { useState } from "react";
import {
  File as FileIcon,
  Info,
  Loader2,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import ImportFileRow from "@/components/import/ImportFileRow";
import {
  useImportCandidates,
  useImportRemoteCandidates,
} from "@/hooks/useImport";
import { ago } from "@/lib/healthRows";
import { detectImportSearchMode, getImportIssueLabel } from "@/lib/importUtils";
import {
  candidateMeta,
  candidateTitle,
  formatBytes,
  mergeCandidates,
  pickNote,
  wantsProviderSearch,
} from "@/lib/importPick";
import { seriesCoverSrc } from "@/lib/series-utils";
import { cn } from "@/lib/utils";
import type {
  ImportBucket,
  ImportCandidate,
  ImportFile,
  ImportGroup,
} from "@/types";

const FILES_SHOWN = 3;

function CandidateCover({ candidate }: { candidate: ImportCandidate }) {
  const [failed, setFailed] = useState(false);
  const src = candidate.in_library
    ? seriesCoverSrc(candidate.comic_id)
    : candidate.image;
  if (!src || failed) {
    return (
      <span
        aria-hidden="true"
        className="h-12 w-8 shrink-0 rounded-sm bg-surface-3"
      />
    );
  }
  return (
    <img
      src={src}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
      className="h-12 w-8 shrink-0 rounded-sm object-cover"
    />
  );
}

function groupTitle(group: ImportGroup): string {
  return `${group.ComicName}${group.Volume ? ` v${group.Volume}` : ""}${
    group.ComicYear ? ` (${group.ComicYear})` : ""
  }`;
}

/**
 * The pick panel (v2 Import design): which series a review group is, why it
 * stopped for a person, its files, and the one action that settles it.
 * Candidates are scored by the same matcher the inbox scan uses; series not
 * in the library come from a provider search only when the library leaves the
 * pick thin, because that search costs an API call.
 */
export default function ImportPickPanel({
  group,
  bucket,
  rowId,
  onClose,
  onImport,
  onIgnore,
  onDelete,
  onSearchDifferent,
  onIssueNumberChange,
  isBusy = false,
  isImporting = false,
  isMetadataSaving = false,
}: {
  group: ImportGroup;
  bucket: ImportBucket;
  /** The table row id; MatchModal returns focus to the element carrying it. */
  rowId: string;
  onClose: () => void;
  onImport: (candidate: ImportCandidate) => void;
  onIgnore: (ignore: boolean) => void;
  onDelete: () => void;
  onSearchDifferent: (trigger: HTMLElement) => void;
  onIssueNumberChange?: (
    file: ImportFile,
    issueNumber: string,
  ) => Promise<void>;
  isBusy?: boolean;
  isImporting?: boolean;
  isMetadataSaving?: boolean;
}) {
  const impIds = group.files.map((file) => file.impID);
  const panelQuery = useImportCandidates(impIds);
  const panel = panelQuery.data;
  const remoteQuery = useImportRemoteCandidates(
    impIds,
    detectImportSearchMode(group),
    !!panel && wantsProviderSearch(panel),
  );
  const [chosenId, setChosenId] = useState<string | null>(null);
  const [showAllFiles, setShowAllFiles] = useState(false);
  const [editingNumbers, setEditingNumbers] = useState(false);

  const candidates = panel
    ? mergeCandidates(panel.candidates, remoteQuery.data?.candidates)
    : [];
  const selectedId = chosenId ?? panel?.pick ?? candidates[0]?.comic_id;
  const selected =
    candidates.find((candidate) => candidate.comic_id === selectedId) ?? null;

  const fileCount = group.FileCount ?? group.files.length;
  const size = formatBytes(panel?.total_bytes);
  const found = panel?.found_at
    ? `found in ${panel.source === "inbox" ? "inbox" : "a library scan"} ${ago(
        new Date(panel.found_at),
      )}`
    : null;
  const meta = [
    `${fileCount} file${fileCount === 1 ? "" : "s"}`,
    size,
    found,
  ].filter(Boolean);

  const sizes = new Map(
    (panel?.files ?? []).map((file) => [file.impID, file.bytes]),
  );
  const files = showAllFiles ? group.files : group.files.slice(0, FILES_SHOWN);
  const hidden = group.files.length - files.length;
  const ignored =
    bucket === "ignored" ||
    (group.files.length > 0 && group.files.every((f) => f.IgnoreFile === 1));
  const title = groupTitle(group);

  return (
    <aside
      aria-label={`Pick a series for ${title}`}
      data-testid="import-pick-panel"
      className="flex min-h-0 flex-col rounded-lg border border-border-subtle bg-surface-1"
    >
      <div className="flex items-start gap-3 border-b border-border-subtle px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[15px] font-semibold text-foreground">
            {title}
          </h2>
          <p className="mt-0.5 text-xs text-foreground-2">{meta.join(" · ")}</p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="Close pick panel"
          onClick={onClose}
        >
          <X />
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {panelQuery.isLoading && (
          <div className="space-y-2 p-4">
            <Skeleton className="h-10" />
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </div>
        )}
        {panelQuery.error && (
          <p className="p-4 text-sm text-destructive">
            Unable to load candidates: {panelQuery.error.message}
          </p>
        )}

        {panel && (
          <>
            <p className="flex gap-2 border-b border-border-subtle px-4 py-3 text-xs leading-relaxed text-foreground-2">
              <Info
                aria-hidden="true"
                className="mt-0.5 size-3.5 shrink-0 text-muted-foreground"
              />
              <span>{pickNote(panel)}</span>
            </p>

            <section className="px-4 pt-4">
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">
                Pick a series
              </h3>
              {candidates.length > 0 ? (
                <div
                  role="radiogroup"
                  aria-label="Pick a series"
                  className="space-y-2"
                >
                  {candidates.map((candidate) => {
                    const checked = candidate.comic_id === selectedId;
                    return (
                      <label
                        key={candidate.comic_id}
                        className={cn(
                          "flex cursor-pointer items-center gap-3 rounded-md border px-3 py-2 transition-colors",
                          checked
                            ? "border-border-strong bg-surface-2"
                            : "border-border-subtle hover:bg-surface-2",
                        )}
                      >
                        <input
                          type="radio"
                          name={`pick-${group.DynamicName}`}
                          value={candidate.comic_id}
                          checked={checked}
                          onChange={() => setChosenId(candidate.comic_id)}
                          className="size-4 shrink-0 accent-[var(--foreground)]"
                        />
                        <CandidateCover candidate={candidate} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm text-foreground">
                            {candidateTitle(candidate)}
                          </span>
                          <span className="block truncate text-xs text-foreground-2">
                            {candidateMeta(candidate)}
                          </span>
                        </span>
                        <span className="font-mono text-[11px] tabular-nums text-foreground-2">
                          {candidate.score}%
                        </span>
                      </label>
                    );
                  })}
                </div>
              ) : (
                !remoteQuery.isFetching && (
                  <p className="text-sm text-foreground-2">
                    No series scored close enough to suggest.
                  </p>
                )
              )}
              {remoteQuery.isFetching && (
                <p className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="size-3 animate-spin" />
                  Looking for series outside your library…
                </p>
              )}
              {remoteQuery.data?.error && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Provider search unavailable: {remoteQuery.data.error}
                </p>
              )}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="mt-2 -ml-2 text-foreground-2"
                data-import-match={rowId}
                onClick={(event) => onSearchDifferent(event.currentTarget)}
              >
                <Search />
                Search for a different series
              </Button>
            </section>
          </>
        )}

        <section className="px-4 pb-4 pt-3">
          <div className="mb-1 flex items-center justify-between gap-2">
            <h3 className="text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">
              Files
            </h3>
            {onIssueNumberChange && (
              <button
                type="button"
                aria-pressed={editingNumbers}
                onClick={() => setEditingNumbers((value) => !value)}
                className="text-xs text-foreground-2 underline-offset-2 hover:text-foreground hover:underline"
              >
                {editingNumbers
                  ? "Done"
                  : `Edit ${getImportIssueLabel(group).toLowerCase()} numbers`}
              </button>
            )}
          </div>
          {editingNumbers ? (
            <div className="-mx-4">
              {group.files.map((file) => (
                <ImportFileRow
                  key={`${file.impID}-${file.IssueNumber ?? ""}`}
                  file={file}
                  label={getImportIssueLabel(group)}
                  onIssueNumberChange={onIssueNumberChange}
                  isMetadataSaving={isMetadataSaving}
                />
              ))}
            </div>
          ) : (
            <>
              <ul className="space-y-1">
                {files.map((file) => (
                  <li
                    key={file.impID}
                    className="flex items-center gap-2 py-1 text-xs"
                  >
                    <FileIcon
                      aria-hidden="true"
                      className="size-3.5 shrink-0 text-muted-foreground"
                    />
                    <span
                      className="min-w-0 flex-1 truncate font-mono text-foreground-2"
                      title={file.ComicFilename}
                    >
                      {file.ComicFilename}
                    </span>
                    <span className="shrink-0 mono-meta">
                      {formatBytes(sizes.get(file.impID))}
                    </span>
                  </li>
                ))}
              </ul>
              {hidden > 0 && (
                <button
                  type="button"
                  onClick={() => setShowAllFiles(true)}
                  className="mt-1 text-xs text-foreground-2 hover:text-foreground"
                >
                  + {hidden} more
                </button>
              )}
            </>
          )}
        </section>
      </div>

      <div className="flex items-center gap-2 border-t border-border-subtle px-4 py-3">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={isBusy}
          onClick={() => onIgnore(!ignored)}
        >
          {ignored ? "Unignore" : "Ignore"}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="Delete import record"
          title="Delete the import record (files on disk are untouched)"
          disabled={isBusy}
          className="text-muted-foreground hover:text-destructive"
          onClick={onDelete}
        >
          <Trash2 />
        </Button>
        <Button
          type="button"
          size="sm"
          className="ml-auto max-w-[70%]"
          disabled={!selected || isBusy}
          onClick={() => selected && onImport(selected)}
        >
          {isImporting && <Loader2 className="animate-spin" />}
          <span className="truncate">
            {selected
              ? `${selected.in_library ? "Import" : "Add and import"} as ${candidateTitle(selected)}`
              : "Pick a series"}
          </span>
        </Button>
      </div>
    </aside>
  );
}
