import { useState } from "react";
import { EyeOff, Eye } from "lucide-react";
import {
  useImportPending,
  useMatchImport,
  useIgnoreImport,
  useDeleteImport,
} from "@/hooks/useImport";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import ImportTable from "@/components/import/ImportTable";
import ImportBulkActions from "@/components/import/ImportBulkActions";
import MatchModal from "@/components/import/MatchModal";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import LibraryScanSection from "@/components/import/LibraryScanSection";
import ImportInboxSection from "@/components/import/ImportInboxSection";
import PageHeader from "@/components/layout/PageHeader";
import type { ImportGroup } from "@/types";

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

  const matchImportMutation = useMatchImport();
  const ignoreImportMutation = useIgnoreImport();
  const deleteImportMutation = useDeleteImport();
  const { addToast } = useToast();

  const handleMatchClick = (group: ImportGroup) => {
    setMatchingGroup(group);
    setMatchModalOpen(true);
  };

  const handleMatch = async (comicId: string, comicName: string) => {
    if (!matchingGroup) return;
    const impIds = matchingGroup.files.map((f) => f.impID);
    try {
      await matchImportMutation.mutateAsync({ impIds, comicId });
      addToast({
        type: "success",
        message: `Matched ${impIds.length} file${impIds.length !== 1 ? "s" : ""} to ${comicName}`,
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
      setSelectedIds([]);
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
      setSelectedIds([]);
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
      setSelectedIds([]);
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to delete records: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const pendingCount = pagination?.total ?? imports.length;

  return (
    <div className="page-transition">
      <PageHeader
        title="Import"
        meta={
          isLoading
            ? "loading…"
            : `${pendingCount} file${pendingCount === 1 ? "" : "s"} awaiting review`
        }
      />

      <div className="px-5 py-5 space-y-8">
        {/* Library scan */}
        <section>
          <SectionHeader
            label="LIBRARY · SCAN"
            title="Scan existing directories"
            meta="Find and import series already present on disk."
          />
          <LibraryScanSection />
        </section>

        {/* Inbox */}
        <section>
          <SectionHeader
            label="INBOX · AUTO-MATCH"
            title="Monitor an import directory"
            meta="Drop files into a watched folder to auto-match against your library."
          />
          <ImportInboxSection />
        </section>

        {/* Pending */}
        <section>
          <SectionHeader
            label="PENDING · REVIEW"
            title="Files awaiting review"
            meta={`${pendingCount} file${pendingCount === 1 ? "" : "s"} need a match before being imported.`}
          />

          <div className="flex items-center gap-3 mb-4">
            <button
              type="button"
              aria-pressed={showIgnored}
              onClick={() => {
                setShowIgnored((prev) => !prev);
                setPage(0);
                setSelectedIds([]);
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

          {!isLoading && !error && (
            <ImportTable
              imports={imports}
              pagination={pagination}
              onNextPage={() => {
                setPage((p) => p + 1);
                setSelectedIds([]);
              }}
              onPrevPage={() => {
                setPage((p) => Math.max(0, p - 1));
                setSelectedIds([]);
              }}
              onSelectionChange={setSelectedIds}
              onMatchClick={handleMatchClick}
            />
          )}

          <ImportBulkActions
            selectedCount={selectedIds.length}
            onIgnore={handleBulkIgnore}
            onUnignore={handleBulkUnignore}
            onDelete={handleBulkDelete}
            onClear={() => setSelectedIds([])}
            isLoading={
              ignoreImportMutation.isPending || deleteImportMutation.isPending
            }
            showUnignore={showIgnored}
          />
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
