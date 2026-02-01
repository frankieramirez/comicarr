import { useState } from "react";
import { RefreshCw, EyeOff, Eye } from "lucide-react";
import {
  useImportPending,
  useMatchImport,
  useIgnoreImport,
  useDeleteImport,
  useRefreshImport,
} from "@/hooks/useImport";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import ImportTable from "@/components/import/ImportTable";
import ImportBulkActions from "@/components/import/ImportBulkActions";
import MatchModal from "@/components/import/MatchModal";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import type { ImportGroup } from "@/types";

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
  const refreshImportMutation = useRefreshImport();
  const { addToast } = useToast();

  const handleRefreshImport = async () => {
    try {
      await refreshImportMutation.mutateAsync();
      addToast({
        type: "info",
        message: "Import scan started. This may take a few moments.",
      });
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to start import scan: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

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
        `Are you sure you want to delete ${selectedIds.length} import record${selectedIds.length !== 1 ? "s" : ""}? This will not delete the actual files.`,
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

  const handleClearSelection = () => {
    setSelectedIds([]);
  };

  const handleNextPage = () => {
    setPage((p) => p + 1);
    setSelectedIds([]);
  };

  const handlePrevPage = () => {
    setPage((p) => Math.max(0, p - 1));
    setSelectedIds([]);
  };

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 page-transition">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-foreground mb-2">
          Import Management
        </h1>
        <p className="text-muted-foreground">
          {pagination?.total || imports.length} pending import
          {(pagination?.total || imports.length) !== 1 ? "s" : ""}
        </p>
      </div>

      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-4">
          <div className="flex items-center space-x-2">
            <Checkbox
              id="show-ignored"
              checked={showIgnored}
              onChange={() => setShowIgnored(!showIgnored)}
            />
            <Label htmlFor="show-ignored" className="text-sm cursor-pointer">
              {showIgnored ? (
                <span className="flex items-center gap-1">
                  <Eye className="w-4 h-4" /> Show Ignored
                </span>
              ) : (
                <span className="flex items-center gap-1">
                  <EyeOff className="w-4 h-4" /> Hide Ignored
                </span>
              )}
            </Label>
          </div>
        </div>

        <Button
          onClick={handleRefreshImport}
          disabled={refreshImportMutation.isPending}
        >
          <RefreshCw
            className={`w-4 h-4 mr-2 ${refreshImportMutation.isPending ? "animate-spin" : ""}`}
          />
          Scan Import Directory
        </Button>
      </div>

      {isLoading && (
        <div className="space-y-4">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
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
          onNextPage={handleNextPage}
          onPrevPage={handlePrevPage}
          onSelectionChange={setSelectedIds}
          onMatchClick={handleMatchClick}
        />
      )}

      <ImportBulkActions
        selectedCount={selectedIds.length}
        onIgnore={handleBulkIgnore}
        onUnignore={handleBulkUnignore}
        onDelete={handleBulkDelete}
        onClear={handleClearSelection}
        isLoading={
          ignoreImportMutation.isPending || deleteImportMutation.isPending
        }
        showUnignore={showIgnored}
      />

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
