import { ph, plural, t } from "@lingui/core/macro";
import { errorText } from "@/lib/api";
import { Trans } from "@lingui/react/macro";
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
import { formatNumber } from "@/lib/intl";

const TABS = (): Array<[ImportBucket, string]> => [
  ["needs_pick", t`Needs a pick`],
  ["confident", t`Confident`],
  ["ignored", t`Ignored`],
];

const EMPTY_COPY = (): Record<ImportBucket, [string, string]> => ({
  needs_pick: [
    t`Nothing needs a pick`,
    t`Every file Comicarr found is matched or set aside.`,
  ],
  confident: [
    t`No confident matches waiting`,
    t`Groups that clear your auto-import bar but did not import on their own wait here.`,
  ],
  ignored: [
    t`No ignored files`,
    t`Files you ignore wait here until you bring them back.`,
  ],
});

function importedAs(files: number, series: string): string {
  return plural(files, {
    one: `Imported # file as ${series}`,
    other: `Imported # files as ${series}`,
  });
}

function filesIgnored(files: number, ignore: boolean): string {
  return ignore
    ? plural(files, { one: "# file ignored", other: "# files ignored" })
    : plural(files, { one: "# file unignored", other: "# files unignored" });
}

function recordsDeleted(records: number): string {
  return plural(records, {
    one: "# import record deleted",
    other: "# import records deleted",
  });
}

function deleteRecordsPrompt(records: number): string {
  return plural(records, {
    one: "Delete # import record? (Files on disk are untouched.)",
    other: "Delete # import records? (Files on disk are untouched.)",
  });
}

function confidentSummary(result: {
  imported: number;
  groups: number;
  failed: { name: string; error: string }[];
}): string {
  const files = plural(result.imported, {
    one: "Imported # file",
    other: "Imported # files",
  });
  const first = result.failed[0];
  if (first) {
    const groups = plural(result.failed.length, {
      one: "# group failed",
      other: "# groups failed",
    });
    return t`${files}; ${groups} (${ph({ name: first.name })}: ${ph({ error: first.error })})`;
  }
  return plural(result.groups, {
    one: `${files} from # confident match`,
    other: `${files} from # confident matches`,
  });
}

/** "3 groups · 12 files awaiting review". */
function pendingSummary(groups: number, files: number): string {
  const groupCount = plural(groups, { one: "# group", other: "# groups" });
  const fileCount = plural(files, { one: "# file", other: "# files" });
  return t`${groupCount} · ${fileCount} awaiting review`;
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
    ? t`Unable to load pending imports`
    : pendingSummary(groupCount, fileCount);
  const pendingReviewHelp = error
    ? t`Resolve the loading error before reviewing imports.`
    : t`${pendingReviewMeta}. Pick a group to see the series it could be.`;

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
        message: importedAs(impIds.length, candidateTitle(candidate)),
      });
    } catch (err) {
      addToast({
        type: "error",
        message: t`Failed to import: ${ph({ error: errorText(err) })}`,
      });
    }
  }

  async function handleImportConfident() {
    try {
      const result = await importConfidentMutation.mutateAsync();
      const failed = result.failed.length;
      addToast({
        type: failed ? "error" : "success",
        message: confidentSummary(result),
      });
    } catch (err) {
      addToast({
        type: "error",
        message: t`Failed to import confident matches: ${ph({ error: errorText(err) })}`,
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
        message: importedAs(impIds.length, comicName),
      });
      setMatchModalOpen(false);
      setMatchingGroup(null);
    } catch (err) {
      addToast({
        type: "error",
        message: t`Failed to match: ${ph({ error: errorText(err) })}`,
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
        message: t`Failed to update import metadata: ${ph({ error: errorText(err) })}`,
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
        message: filesIgnored(impIds.length, ignore),
      });
      clearSelection();
    } catch (err) {
      addToast({
        type: "error",
        message: ignore
          ? t`Failed to ignore files: ${ph({ error: errorText(err) })}`
          : t`Failed to unignore files: ${ph({ error: errorText(err) })}`,
      });
    }
  }

  async function handleGroupDelete(group: ImportGroup) {
    const impIds = group.files.map((f) => f.impID);
    if (!window.confirm(deleteRecordsPrompt(impIds.length))) {
      return;
    }
    try {
      await deleteImportMutation.mutateAsync(impIds);
      addToast({
        type: "success",
        message: recordsDeleted(impIds.length),
      });
      clearSelection();
    } catch (err) {
      addToast({
        type: "error",
        message: t`Failed to delete records: ${ph({ error: errorText(err) })}`,
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
        message: filesIgnored(selectedFileIds.length, true),
      });
      clearSelection();
    } catch (err) {
      addToast({
        type: "error",
        message: t`Failed to ignore files: ${ph({ error: errorText(err) })}`,
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
        message: filesIgnored(selectedFileIds.length, false),
      });
      clearSelection();
    } catch (err) {
      addToast({
        type: "error",
        message: t`Failed to unignore files: ${ph({ error: errorText(err) })}`,
      });
    }
  };

  const handleBulkDelete = async () => {
    if (!window.confirm(deleteRecordsPrompt(selectedFileIds.length))) {
      return;
    }
    try {
      await deleteImportMutation.mutateAsync(selectedFileIds);
      addToast({
        type: "success",
        message: recordsDeleted(selectedFileIds.length),
      });
      clearSelection();
    } catch (err) {
      addToast({
        type: "error",
        message: t`Failed to delete records: ${ph({ error: errorText(err) })}`,
      });
    }
  };

  const handleScanInboxNow = async () => {
    try {
      await refreshImportMutation.mutateAsync();
      addToast({
        type: "success",
        message: t`Import inbox scan started`,
      });
    } catch (err) {
      addToast({
        type: "error",
        message: t`Failed to scan inbox: ${ph({ error: errorText(err) })}`,
      });
    }
  };

  const importDirectoryConfigured = Boolean(appConfig?.import_dir);

  return (
    <div className="page-transition flex h-full min-h-0 flex-col">
      <PageHeader
        title={t`Import`}
        meta={
          isLoading
            ? "loading…"
            : error
              ? pendingReviewMeta
              : t`Files Comicarr found but couldn't place on its own. Confirm a series and they move into your library.`
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
                  ? t`Scan the watched inbox for new files`
                  : t`Set an import directory first`
              }
            >
              <RefreshCw
                className={
                  refreshImportMutation.isPending ? "animate-spin" : ""
                }
              />
              <Trans>Scan now</Trans>
            </Button>
            {confidentCount > 0 && (
              <Button
                type="button"
                variant="outline"
                size="toolbar"
                onClick={() => void handleImportConfident()}
                disabled={importConfidentMutation.isPending}
                title={t`Import every Confident group as its suggested series`}
              >
                <CheckCheck />
                {plural(confidentCount, {
                  one: "Import # confident match",
                  other: "Import # confident matches",
                })}
              </Button>
            )}
          </>
        }
      />

      {/* Import stacks several sections, so the whole body scrolls as one. */}
      <div className="flex-1 min-h-0 overflow-auto px-8 pb-8 space-y-8">
        <ImportSourcesStrip />

        {/* Review queue */}
        <section aria-label={t`Files awaiting review`}>
          <h2 className="sr-only">
            <Trans>Files awaiting review</Trans>
          </h2>
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <div
              role="group"
              aria-label={t`Review queue`}
              className={SEGMENTED_GROUP}
            >
              {TABS().map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={bucket === value}
                  onClick={() => switchBucket(value)}
                  className={SEGMENTED_ITEM}
                >
                  {label}
                  {buckets && (
                    <span className="ms-1.5 mono-meta">
                      {formatNumber(buckets[value])}
                    </span>
                  )}
                </button>
              ))}
            </div>
            <div className="relative w-full max-w-60 max-sm:max-w-none">
              <Search
                aria-hidden="true"
                className="pointer-events-none absolute start-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                type="search"
                aria-label={t`Filter files`}
                placeholder={t`Filter files`}
                value={filter}
                onChange={(event) => {
                  setFilter(event.target.value);
                  setOpenRowId(undefined);
                  resetPage();
                  clearSelection();
                }}
                className="h-8 ps-8 text-sm"
              />
            </div>
            <p className="sr-only" aria-live="polite">
              {isLoading ? t`Loading review groups.` : pendingReviewHelp}
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
              title={t`Unable to load pending imports`}
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
                      {plural(confidentCount, {
                        one: "# more matched with high confidence. It waits under Confident so you can import it in one go.",
                        other:
                          "# more matched with high confidence. They wait under Confident so you can import them in one go.",
                      })}
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
                          ? t`Nothing matches that filter`
                          : bucket === "needs_pick" && !confidentCount
                            ? t`No pending imports`
                            : EMPTY_COPY()[bucket][0]}
                      </div>
                      <div className="mt-1 max-w-xl text-sm text-foreground-2">
                        {search.trim()
                          ? t`Clear the filter to see every group in this tab.`
                          : bucket === "needs_pick" && !confidentCount
                            ? t`The review queue is clear. Scan the watched inbox to check for new files.`
                            : EMPTY_COPY()[bucket][1]}
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
                        <Trans>Scan inbox now</Trans>
                      </Button>
                    ) : (
                      <span className="mono-meta uppercase tracking-wider">
                        <Trans>Import directory not configured</Trans>
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
          <SectionHeader title={t`Sources and scans`} />
          <p className="mb-4 text-[13px] text-foreground-2">
            <Trans>
              Find series already on disk, or check the watched inbox now.
            </Trans>
          </p>
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(20rem,0.65fr)]">
            <div>
              <h3 className="mb-2 text-[13px] font-semibold text-foreground">
                <Trans>Scan existing directories</Trans>
              </h3>
              <LibraryScanSection />
            </div>
            <div>
              <h3 className="mb-2 text-[13px] font-semibold text-foreground">
                <Trans>Watched inbox</Trans>
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
