import { SEGMENTED_GROUP, SEGMENTED_ITEM } from "@/lib/segmented";
import { useDeferredValue, useMemo, useState } from "react";
import { CheckCheck, Inbox, RefreshCw, Search } from "lucide-react";
import {
  useImportConfident,
  useImportPending,
  useMatchImport,
  useIgnoreImport,
  useDeleteImport,
  useUpdateImportMetadata,
  useRefreshImport,
} from "@/hooks/useImport";
import { useConfig } from "@/hooks/useConfig";
import { useIsMobile } from "@/hooks/use-mobile";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import ImportTable from "@/components/import/ImportTable";
import {
  getImportGroupRowId,
  getSelectedImportFileIds,
  useImportColumns,
} from "@/components/import/importColumns";
import ImportBulkActions from "@/components/import/ImportBulkActions";
import ImportPickPanel from "@/components/import/ImportPickPanel";
import MatchModal from "@/components/import/MatchModal";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import LibraryScanSection from "@/components/import/LibraryScanSection";
import ImportInboxSection from "@/components/import/ImportInboxSection";
import PageHeader from "@/components/layout/PageHeader";
import { SectionHeader } from "@/components/dashboard/DashboardPanel";
import { candidateTitle } from "@/lib/importPick";
import ImportSourcesStrip from "@/components/import/ImportSourcesStrip";
import { useServerPage } from "@/components/data-table/useServerPage";
import { useTableState } from "@/components/data-table/useTableState";
import type { ImportBucket, ImportCandidate, ImportGroup } from "@/types";

const TABS: Array<[ImportBucket, string]> = [
  ["needs_pick", "Needs a pick"],
  ["confident", "Confident"],
  ["ignored", "Ignored"],
];

const EMPTY_COPY: Record<ImportBucket, [string, string]> = {
  needs_pick: [
    "Nothing needs a pick",
    "Every file Comicarr found is matched or set aside.",
  ],
  confident: [
    "No confident matches waiting",
    "Groups that clear your auto-import bar but did not import on their own wait here.",
  ],
  ignored: [
    "No ignored files",
    "Files you ignore wait here until you bring them back.",
  ],
};

function pluralize(count: number, singular: string, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

export default function ImportPage() {
  const { limit, offset, nextPage, prevPage, resetPage } = useServerPage(50);
  const [bucket, setBucket] = useState<ImportBucket>("needs_pick");
  const [filter, setFilter] = useState("");
  const search = useDeferredValue(filter);
  /** undefined: the default (first row on wide screens); null: closed. */
  const [openRowId, setOpenRowId] = useState<string | null | undefined>();
  const isMobile = useIsMobile();
  const [matchModalOpen, setMatchModalOpen] = useState(false);
  const [matchingGroup, setMatchingGroup] = useState<ImportGroup | null>(null);
  const [matchTrigger, setMatchTrigger] = useState<HTMLElement | null>(null);
  const [matchTriggerId, setMatchTriggerId] = useState<string | null>(null);

  const { data, isLoading, error, refetch } = useImportPending(
    limit,
    offset,
    bucket,
    search,
  );
  const imports = data?.imports || [];
  const pagination = data?.pagination;
  const summary = data?.summary;
  const buckets = summary?.buckets;
  const confidentCount = buckets?.confident ?? 0;
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
    : `${pendingReviewMeta}. Pick a group to see the series it could be.`;

  const matchImportMutation = useMatchImport();
  const ignoreImportMutation = useIgnoreImport();
  const deleteImportMutation = useDeleteImport();
  const updateImportMetadataMutation = useUpdateImportMetadata();
  const refreshImportMutation = useRefreshImport();
  const importConfidentMutation = useImportConfident();
  const { data: appConfig } = useConfig();
  const { addToast } = useToast();

  const columns = useImportColumns();
  const isActionLoading =
    matchImportMutation.isPending ||
    ignoreImportMutation.isPending ||
    deleteImportMutation.isPending;

  const { table, selectedRows, clearSelection } = useTableState({
    data: imports,
    columns,
    getRowId: getImportGroupRowId,
    selection: { scope: "filtered" },
  });

  const rowIds = imports.map(getImportGroupRowId);
  const resolvedOpenId =
    openRowId && rowIds.includes(openRowId)
      ? openRowId
      : openRowId === null || isMobile
        ? null
        : (rowIds[0] ?? null);
  const openGroup =
    imports.find((group) => getImportGroupRowId(group) === resolvedOpenId) ??
    null;

  function switchBucket(next: ImportBucket) {
    setBucket(next);
    setOpenRowId(undefined);
    resetPage();
    clearSelection();
  }

  async function handlePanelImport(
    group: ImportGroup,
    candidate: ImportCandidate,
  ) {
    const impIds = group.files.map((f) => f.impID);
    try {
      await matchImportMutation.mutateAsync({
        impIds,
        comicId: candidate.comic_id,
        comicName: candidate.name,
        addMissing: !candidate.in_library,
      });
      addToast({
        type: "success",
        message: `Imported ${impIds.length} file${impIds.length !== 1 ? "s" : ""} as ${candidateTitle(candidate)}`,
      });
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to import: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  }

  async function handleImportConfident() {
    try {
      const result = await importConfidentMutation.mutateAsync();
      const failed = result.failed.length;
      addToast({
        type: failed ? "error" : "success",
        message: failed
          ? `Imported ${result.imported} file${result.imported === 1 ? "" : "s"}; ${failed} group${failed === 1 ? "" : "s"} failed (${result.failed[0].name}: ${result.failed[0].error})`
          : `Imported ${result.imported} file${result.imported === 1 ? "" : "s"} from ${result.groups} confident match${result.groups === 1 ? "" : "es"}`,
      });
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to import confident matches: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  }

  const selectedFileIds = useMemo(
    () => getSelectedImportFileIds(selectedRows),
    [selectedRows],
  );
  const selectedGroupCount = selectedRows.length;

  function handleSearchDifferent(group: ImportGroup, trigger?: HTMLElement) {
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
          <>
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
                className={
                  refreshImportMutation.isPending ? "animate-spin" : ""
                }
              />
              Scan now
            </Button>
            {confidentCount > 0 && (
              <Button
                type="button"
                variant="outline"
                size="toolbar"
                onClick={() => void handleImportConfident()}
                disabled={importConfidentMutation.isPending}
                title="Import every Confident group as its suggested series"
              >
                <CheckCheck />
                Import {confidentCount.toLocaleString()} confident match
                {confidentCount === 1 ? "" : "es"}
              </Button>
            )}
          </>
        }
      />

      {/* Import stacks several sections, so the whole body scrolls as one. */}
      <div className="flex-1 min-h-0 overflow-auto px-8 pb-8 space-y-8">
        <ImportSourcesStrip />

        {/* Review queue */}
        <section aria-label="Files awaiting review">
          <h2 className="sr-only">Files awaiting review</h2>
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <div
              role="group"
              aria-label="Review queue"
              className={SEGMENTED_GROUP}
            >
              {TABS.map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={bucket === value}
                  onClick={() => switchBucket(value)}
                  className={SEGMENTED_ITEM}
                >
                  {label}
                  {buckets && (
                    <span className="ml-1.5 mono-meta">
                      {buckets[value].toLocaleString()}
                    </span>
                  )}
                </button>
              ))}
            </div>
            <div className="relative w-full max-w-60 max-sm:max-w-none">
              <Search
                aria-hidden="true"
                className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                type="search"
                aria-label="Filter files"
                placeholder="Filter files"
                value={filter}
                onChange={(event) => {
                  setFilter(event.target.value);
                  setOpenRowId(undefined);
                  resetPage();
                  clearSelection();
                }}
                className="h-8 pl-8 text-sm"
              />
            </div>
            <p className="sr-only" aria-live="polite">
              {isLoading ? "Loading review groups." : pendingReviewHelp}
            </p>
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
              <div
                className={
                  openGroup
                    ? "grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(22rem,26rem)]"
                    : undefined
                }
              >
                <div className="min-w-0">
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
                    onOpenGroup={(group) =>
                      setOpenRowId(getImportGroupRowId(group))
                    }
                    openRowId={resolvedOpenId}
                  />
                  {bucket === "needs_pick" && confidentCount > 0 && (
                    <p className="mt-3 flex items-center gap-2 text-xs text-foreground-2">
                      <CheckCheck
                        aria-hidden="true"
                        className="size-3.5 text-muted-foreground"
                      />
                      {confidentCount.toLocaleString()} more matched with high
                      confidence. They wait under Confident so you can import
                      them in one go.
                    </p>
                  )}
                </div>
                {openGroup && (
                  <div className="lg:sticky lg:top-0 lg:[&>aside]:max-h-[max(28rem,calc(100vh-18.5rem))]">
                    <ImportPickPanel
                      key={resolvedOpenId}
                      group={openGroup}
                      bucket={bucket}
                      rowId={resolvedOpenId ?? ""}
                      onClose={() => setOpenRowId(null)}
                      onImport={(candidate) =>
                        void handlePanelImport(openGroup, candidate)
                      }
                      onIgnore={(ignore) =>
                        void handleGroupIgnore(openGroup, ignore)
                      }
                      onDelete={() => void handleGroupDelete(openGroup)}
                      onSearchDifferent={(trigger) =>
                        handleSearchDifferent(openGroup, trigger)
                      }
                      onIssueNumberChange={handleIssueNumberChange}
                      isBusy={isActionLoading}
                      isImporting={matchImportMutation.isPending}
                      isMetadataSaving={updateImportMetadataMutation.isPending}
                    />
                  </div>
                )}
              </div>
            ) : (
              <div className="rounded-lg border border-dashed border-border-subtle px-5 py-8">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 rounded-md border border-border-subtle bg-surface-1 p-2">
                      <Inbox className="h-4 w-4 text-muted-foreground" />
                    </div>
                    <div>
                      <div className="text-sm font-semibold">
                        {search.trim()
                          ? "Nothing matches that filter"
                          : bucket === "needs_pick" && !confidentCount
                            ? "No pending imports"
                            : EMPTY_COPY[bucket][0]}
                      </div>
                      <div className="mt-1 max-w-xl text-sm text-foreground-2">
                        {search.trim()
                          ? "Clear the filter to see every group in this tab."
                          : bucket === "needs_pick" && !confidentCount
                            ? "The review queue is clear. Scan the watched inbox to check for new files."
                            : EMPTY_COPY[bucket][1]}
                      </div>
                    </div>
                  </div>
                  {bucket === "needs_pick" &&
                    !search.trim() &&
                    (importDirectoryConfigured ? (
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
                    ))}
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
            showUnignore={bucket === "ignored"}
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
