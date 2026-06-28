import { useState } from "react";
import { EyeOff, Eye, Inbox, RefreshCw } from "lucide-react";
import {
  useImportPending,
  useMatchImport,
  useIgnoreImport,
  useDeleteImport,
  useUpdateImportMetadata,
  useRefreshImport,
} from "@/hooks/useImport";
import { useConfig } from "@/hooks/useConfig";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import ImportTable from "@/components/import/ImportTable";
import ImportBulkActions from "@/components/import/ImportBulkActions";
import MatchModal from "@/components/import/MatchModal";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import LibraryScanSection from "@/components/import/LibraryScanSection";
import ImportInboxSection from "@/components/import/ImportInboxSection";
import PageHeader from "@/components/layout/PageHeader";
import type { ImportGroup } from "@/types";

function pluralize(count: number, singular: string, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function SectionHeader({
  label,
  title,
  meta,
}: {
  label: string;
  title: string;
  meta?: string;
}) {
  return (
    <div className="mb-3">
      <div className="font-mono text-[10px] tracking-[0.12em] uppercase text-muted-foreground mb-1">
        {label}
      </div>
      <div className="text-[14px] font-semibold tracking-tight">{title}</div>
      {meta && (
        <div className="text-[12px] text-muted-foreground mt-0.5">{meta}</div>
      )}
    </div>
  );
}

export default function ImportPage() {
  const [page, setPage] = useState(0);
  const [showIgnored, setShowIgnored] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectedGroupIds, setSelectedGroupIds] = useState<string[]>([]);
  const [matchModalOpen, setMatchModalOpen] = useState(false);
  const [matchingGroup, setMatchingGroup] = useState<ImportGroup | null>(null);
  const limit = 50;
  const offset = page * limit;

  const { data, isLoading, error, refetch } = useImportPending(
    limit,
    offset,
    showIgnored,
  );
  const imports = data?.imports || [];
  const pagination = data?.pagination;
  const summary = data?.summary;
  const visibleFileCount = imports.reduce(
    (total, importGroup) =>
      total + (importGroup.FileCount ?? importGroup.files.length),
    0,
  );
  const groupCount =
    summary?.group_count ?? pagination?.total ?? imports.length;
  const fileCount = summary?.file_count ?? visibleFileCount;
  const pendingReviewMeta = error
    ? "Unable to load pending imports"
    : `${pluralize(groupCount, "group")} · ${pluralize(fileCount, "file")} awaiting review`;
  const pendingReviewHelp = error
    ? "Resolve the loading error before reviewing imports."
    : `${pendingReviewMeta}. Correct chapters or issues, then match a group to import.`;

  const matchImportMutation = useMatchImport();
  const ignoreImportMutation = useIgnoreImport();
  const deleteImportMutation = useDeleteImport();
  const updateImportMetadataMutation = useUpdateImportMetadata();
  const refreshImportMutation = useRefreshImport();
  const { data: appConfig } = useConfig();
  const { addToast } = useToast();

  const handleMatchClick = (group: ImportGroup) => {
    setMatchingGroup(group);
    setMatchModalOpen(true);
  };

  const handleMatch = async (comicId: string, comicName: string) => {
    if (!matchingGroup) return;
    const impIds = matchingGroup.files.map((f) => f.impID);
    try {
      await matchImportMutation.mutateAsync({ impIds, comicId, comicName });
      addToast({
        type: "success",
        message: `Imported ${impIds.length} file${impIds.length !== 1 ? "s" : ""} as ${comicName}`,
      });
      setMatchModalOpen(false);
      setMatchingGroup(null);
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to match: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleIssueNumberChange = async (
    file: ImportGroup["files"][number],
    issueNumber: string,
  ) => {
    try {
      await updateImportMetadataMutation.mutateAsync({
        impId: file.impID,
        issueNumber,
      });
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to update import metadata: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
      throw err;
    }
  };

  const clearSelection = () => {
    setSelectedIds([]);
    setSelectedGroupIds([]);
  };

  const handleSelectionChange = (fileIds: string[], groupIds: string[]) => {
    setSelectedIds(fileIds);
    setSelectedGroupIds(groupIds);
  };

  const handleGroupIgnore = async (group: ImportGroup, ignore: boolean) => {
    const impIds = group.files.map((f) => f.impID);
    try {
      await ignoreImportMutation.mutateAsync({ impIds, ignore });
      addToast({
        type: "success",
        message: `${impIds.length} file${impIds.length !== 1 ? "s" : ""} ${ignore ? "ignored" : "unignored"}`,
      });
      clearSelection();
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to ${ignore ? "ignore" : "unignore"} files: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleGroupDelete = async (group: ImportGroup) => {
    const impIds = group.files.map((f) => f.impID);
    if (
      !window.confirm(
        `Delete ${impIds.length} import record${impIds.length !== 1 ? "s" : ""}? (Files on disk are untouched.)`,
      )
    ) {
      return;
    }
    try {
      await deleteImportMutation.mutateAsync(impIds);
      addToast({
        type: "success",
        message: `${impIds.length} import record${impIds.length !== 1 ? "s" : ""} deleted`,
      });
      clearSelection();
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to delete records: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleBulkIgnore = async () => {
    try {
      await ignoreImportMutation.mutateAsync({
        impIds: selectedIds,
        ignore: true,
      });
      addToast({
        type: "success",
        message: `${selectedIds.length} file${selectedIds.length !== 1 ? "s" : ""} ignored`,
      });
      clearSelection();
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to ignore files: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleBulkUnignore = async () => {
    try {
      await ignoreImportMutation.mutateAsync({
        impIds: selectedIds,
        ignore: false,
      });
      addToast({
        type: "success",
        message: `${selectedIds.length} file${selectedIds.length !== 1 ? "s" : ""} unignored`,
      });
      clearSelection();
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to unignore files: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleBulkDelete = async () => {
    if (
      !window.confirm(
        `Delete ${selectedIds.length} import record${selectedIds.length !== 1 ? "s" : ""}? (Files on disk are untouched.)`,
      )
    ) {
      return;
    }
    try {
      await deleteImportMutation.mutateAsync(selectedIds);
      addToast({
        type: "success",
        message: `${selectedIds.length} import record${selectedIds.length !== 1 ? "s" : ""} deleted`,
      });
      clearSelection();
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to delete records: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleScanInboxNow = async () => {
    try {
      await refreshImportMutation.mutateAsync();
      addToast({
        type: "success",
        message: "Import inbox scan started",
      });
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to scan inbox: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const importDirectoryConfigured = Boolean(appConfig?.import_dir);

  return (
    <div className="page-transition">
      <PageHeader
        title="Import"
        meta={isLoading ? "loading…" : pendingReviewMeta}
      />

      <div className="px-5 py-5 space-y-8">
        {/* Pending */}
        <section>
          <SectionHeader
            label="PENDING · REVIEW"
            title="Files awaiting review"
            meta={isLoading ? "Loading review groups." : pendingReviewHelp}
          />

          <div className="flex items-center gap-3 mb-4">
            <button
              type="button"
              aria-pressed={showIgnored}
              onClick={() => {
                setShowIgnored((prev) => !prev);
                setPage(0);
                clearSelection();
              }}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border font-mono text-[11px]"
              style={{
                borderColor: showIgnored ? "var(--primary)" : "var(--border)",
                color: showIgnored
                  ? "var(--primary)"
                  : "var(--muted-foreground)",
                background: showIgnored
                  ? "color-mix(in oklab, var(--primary) 12%, transparent)"
                  : "transparent",
              }}
            >
              {showIgnored ? (
                <>
                  <Eye className="w-3 h-3" />
                  showing ignored
                </>
              ) : (
                <>
                  <EyeOff className="w-3 h-3" />
                  ignored hidden
                </>
              )}
            </button>
          </div>

          {isLoading && (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-12" />
              ))}
            </div>
          )}

          {error && (
            <ErrorDisplay
              error={error}
              title="Unable to load pending imports"
              onRetry={() => refetch()}
            />
          )}

          {!isLoading &&
            !error &&
            (imports.length > 0 ? (
              <ImportTable
                imports={imports}
                pagination={pagination}
                onNextPage={() => {
                  setPage((p) => p + 1);
                  clearSelection();
                }}
                onPrevPage={() => {
                  setPage((p) => Math.max(0, p - 1));
                  clearSelection();
                }}
                onSelectionChange={handleSelectionChange}
                onMatchClick={handleMatchClick}
                onIgnoreClick={handleGroupIgnore}
                onDeleteClick={handleGroupDelete}
                onIssueNumberChange={handleIssueNumberChange}
                isActionLoading={
                  matchImportMutation.isPending ||
                  ignoreImportMutation.isPending ||
                  deleteImportMutation.isPending
                }
                isMetadataSaving={updateImportMetadataMutation.isPending}
              />
            ) : (
              <div className="rounded-md border border-dashed border-card-border bg-card/40 px-5 py-8">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 rounded-md border border-card-border bg-muted/40 p-2">
                      <Inbox className="h-4 w-4 text-muted-foreground" />
                    </div>
                    <div>
                      <div className="text-sm font-semibold">
                        No pending imports
                      </div>
                      <div className="mt-1 max-w-xl text-sm text-muted-foreground">
                        The review queue is clear. Scan the watched inbox to
                        check for new files.
                      </div>
                    </div>
                  </div>
                  {importDirectoryConfigured ? (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleScanInboxNow}
                      disabled={refreshImportMutation.isPending}
                    >
                      <RefreshCw
                        className={
                          refreshImportMutation.isPending
                            ? "h-4 w-4 animate-spin"
                            : "h-4 w-4"
                        }
                      />
                      Scan inbox now
                    </Button>
                  ) : (
                    <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                      Import directory not configured
                    </span>
                  )}
                </div>
              </div>
            ))}

          <ImportBulkActions
            selectedGroupCount={selectedGroupIds.length}
            selectedFileCount={selectedIds.length}
            onIgnore={handleBulkIgnore}
            onUnignore={handleBulkUnignore}
            onDelete={handleBulkDelete}
            onClear={clearSelection}
            isLoading={
              ignoreImportMutation.isPending || deleteImportMutation.isPending
            }
            showUnignore={showIgnored}
          />
        </section>

        {/* Sources and scans */}
        <section>
          <SectionHeader
            label="SOURCES · SCANS"
            title="Sources and scans"
            meta="Setup and maintenance tools for library directories and the watched inbox."
          />
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(20rem,0.65fr)]">
            <div>
              <SectionHeader
                label="LIBRARY · SCAN"
                title="Scan existing directories"
                meta="Find and import series already present on disk."
              />
              <LibraryScanSection />
            </div>
            <div>
              <SectionHeader
                label="INBOX · AUTO-MATCH"
                title="Monitor an import directory"
                meta="Drop files into a watched folder to auto-match against your library."
              />
              <ImportInboxSection />
            </div>
          </div>
        </section>
      </div>

      <MatchModal
        isOpen={matchModalOpen}
        onClose={() => {
          setMatchModalOpen(false);
          setMatchingGroup(null);
        }}
        importGroup={matchingGroup}
        onMatch={handleMatch}
        isMatching={matchImportMutation.isPending}
      />
    </div>
  );
}
