import { useMemo, useState } from "react";
import { Inbox, RefreshCw } from "lucide-react";
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
import {
  getImportGroupRowId,
  getSelectedImportFileIds,
  useImportColumns,
} from "@/components/import/importColumns";
import ImportBulkActions from "@/components/import/ImportBulkActions";
import MatchModal from "@/components/import/MatchModal";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import LibraryScanSection from "@/components/import/LibraryScanSection";
import ImportInboxSection from "@/components/import/ImportInboxSection";
import PageHeader from "@/components/layout/PageHeader";
import { SectionHeader } from "@/components/dashboard/DashboardPanel";
import ImportSourcesStrip from "@/components/import/ImportSourcesStrip";
import { useServerPage } from "@/components/data-table/useServerPage";
import { useTableState } from "@/components/data-table/useTableState";
import type { ImportGroup } from "@/types";

function pluralize(count: number, singular: string, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

export default function ImportPage() {
  const { limit, offset, nextPage, prevPage, resetPage } = useServerPage(50);
  const [showIgnored, setShowIgnored] = useState(false);
  const [matchModalOpen, setMatchModalOpen] = useState(false);
  const [matchingGroup, setMatchingGroup] = useState<ImportGroup | null>(null);
  const [matchTrigger, setMatchTrigger] = useState<HTMLElement | null>(null);
  const [matchTriggerId, setMatchTriggerId] = useState<string | null>(null);

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

  const columns = useImportColumns({
    onMatchClick: handleMatchClick,
    onIgnoreClick: handleGroupIgnore,
    onDeleteClick: handleGroupDelete,
    isActionLoading:
      matchImportMutation.isPending ||
      ignoreImportMutation.isPending ||
      deleteImportMutation.isPending,
  });

  const { table, selectedRows, clearSelection } = useTableState({
    data: imports,
    columns,
    getRowId: getImportGroupRowId,
    selection: { scope: "filtered" },
    getRowCanExpand: (row) =>
      !!(row.original.files && row.original.files.length > 0),
  });

  const selectedFileIds = useMemo(
    () => getSelectedImportFileIds(selectedRows),
    [selectedRows],
  );
  const selectedGroupCount = selectedRows.length;

  function handleMatchClick(group: ImportGroup, trigger?: HTMLElement) {
    setMatchingGroup(group);
    setMatchTrigger(trigger ?? null);
    setMatchTriggerId(getImportGroupRowId(group));
    setMatchModalOpen(true);
  }

  const handleMatch = async (
    comicId: string,
    comicName: string,
    addMissing: boolean,
  ) => {
    if (!matchingGroup) return;
    const impIds = matchingGroup.files.map((f) => f.impID);
    try {
      await matchImportMutation.mutateAsync({
        impIds,
        comicId,
        comicName,
        addMissing,
      });
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

  async function handleGroupIgnore(group: ImportGroup, ignore: boolean) {
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
  }

  async function handleGroupDelete(group: ImportGroup) {
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
  }

  const handleBulkIgnore = async () => {
    try {
      await ignoreImportMutation.mutateAsync({
        impIds: selectedFileIds,
        ignore: true,
      });
      addToast({
        type: "success",
        message: `${selectedFileIds.length} file${selectedFileIds.length !== 1 ? "s" : ""} ignored`,
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
        impIds: selectedFileIds,
        ignore: false,
      });
      addToast({
        type: "success",
        message: `${selectedFileIds.length} file${selectedFileIds.length !== 1 ? "s" : ""} unignored`,
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
        `Delete ${selectedFileIds.length} import record${selectedFileIds.length !== 1 ? "s" : ""}? (Files on disk are untouched.)`,
      )
    ) {
      return;
    }
    try {
      await deleteImportMutation.mutateAsync(selectedFileIds);
      addToast({
        type: "success",
        message: `${selectedFileIds.length} import record${selectedFileIds.length !== 1 ? "s" : ""} deleted`,
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
    <div className="page-transition flex h-full min-h-0 flex-col">
      <PageHeader
        title="Import"
        meta={
          isLoading
            ? "loading…"
            : error
              ? pendingReviewMeta
              : "Files Comicarr found but couldn't place on its own. Confirm a series and they move into your library."
        }
        actions={
          <Button
            type="button"
            variant="ghost"
            size="toolbar"
            onClick={() => void handleScanInboxNow()}
            disabled={
              !importDirectoryConfigured || refreshImportMutation.isPending
            }
            title={
              importDirectoryConfigured
                ? "Scan the watched inbox for new files"
                : "Set an import directory first"
            }
          >
            <RefreshCw
              className={refreshImportMutation.isPending ? "animate-spin" : ""}
            />
            Scan now
          </Button>
        }
      />

      {/* Import stacks several sections, so the whole body scrolls as one. */}
      <div className="flex-1 min-h-0 overflow-auto px-8 pb-8 space-y-8">
        <ImportSourcesStrip />

        {/* Pending */}
        <section>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <SectionHeader title="Files awaiting review" />
              <p className="text-[13px] text-foreground-2">
                {isLoading ? "Loading review groups." : pendingReviewHelp}
              </p>
            </div>
            <div
              role="group"
              aria-label="Ignored files"
              className="inline-flex rounded-md border border-border-subtle bg-surface-1 p-0.5"
            >
              {(
                [
                  [false, "Pending"],
                  [true, "Include ignored"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={label}
                  type="button"
                  aria-pressed={showIgnored === value}
                  onClick={() => {
                    setShowIgnored(value);
                    resetPage();
                    clearSelection();
                  }}
                  className="h-7 rounded-control px-2.5 text-[13px] text-foreground-2 aria-pressed:bg-surface-3 aria-pressed:font-medium aria-pressed:text-foreground"
                >
                  {label}
                </button>
              ))}
            </div>
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
                table={table}
                pagination={pagination}
                onNextPage={() => {
                  nextPage();
                  clearSelection();
                }}
                onPrevPage={() => {
                  prevPage();
                  clearSelection();
                }}
                onIssueNumberChange={handleIssueNumberChange}
                isMetadataSaving={updateImportMetadataMutation.isPending}
              />
            ) : (
              <div className="rounded-lg border border-dashed border-border-subtle px-5 py-8">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 rounded-md border border-border-subtle bg-surface-1 p-2">
                      <Inbox className="h-4 w-4 text-muted-foreground" />
                    </div>
                    <div>
                      <div className="text-sm font-semibold">
                        No pending imports
                      </div>
                      <div className="mt-1 max-w-xl text-sm text-foreground-2">
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
                    <span className="mono-meta uppercase tracking-wider">
                      Import directory not configured
                    </span>
                  )}
                </div>
              </div>
            ))}

          <ImportBulkActions
            selectedGroupCount={selectedGroupCount}
            selectedFileCount={selectedFileIds.length}
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
          <SectionHeader title="Sources and scans" />
          <p className="mb-4 text-[13px] text-foreground-2">
            Find series already on disk, or check the watched inbox now.
          </p>
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(20rem,0.65fr)]">
            <div>
              <h3 className="mb-2 text-[13px] font-semibold text-foreground">
                Scan existing directories
              </h3>
              <LibraryScanSection />
            </div>
            <div>
              <h3 className="mb-2 text-[13px] font-semibold text-foreground">
                Watched inbox
              </h3>
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
          setMatchTrigger(null);
        }}
        importGroup={matchingGroup}
        onMatch={handleMatch}
        isMatching={matchImportMutation.isPending}
        triggerRowId={matchTriggerId}
        triggerElement={matchTrigger}
      />
    </div>
  );
}
