import { useState, useEffect } from "react";
import { RefreshCw, EyeOff, Eye, BookOpen, Library } from "lucide-react";
import {
  useImportPending,
  useMatchImport,
  useIgnoreImport,
  useDeleteImport,
  useRefreshImport,
  useMangaScan,
  useMangaScanProgress,
} from "@/hooks/useImport";
import { useConfig } from "@/hooks/useConfig";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
  const mangaScanMutation = useMangaScan();
  const { data: appConfig } = useConfig();
  const mangaDirConfigured = !!appConfig?.manga_dir;
  const [mangaScanning, setMangaScanning] = useState(false);
  const { data: mangaProgress } = useMangaScanProgress(mangaScanning);
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

  const handleMangaScan = async () => {
    try {
      await mangaScanMutation.mutateAsync();
      setMangaScanning(true);
      addToast({
        type: "info",
        message: "Manga library scan started. This may take a few moments.",
      });
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to start manga scan: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  // Stop polling when scan reaches a terminal state
  const scanStatus = mangaProgress?.status;
  const scanTerminal =
    mangaScanning && (scanStatus === "completed" || scanStatus === "error");
  useEffect(() => {
    if (!scanTerminal) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Sync polling state with server-driven terminal status
    setMangaScanning(false);
    if (scanStatus === "error") {
      addToast({ type: "error", message: "Manga scan failed" });
    }
  }, [scanTerminal, scanStatus, addToast]);

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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <Card>
          <CardContent className="p-5">
            <div className="flex items-center gap-3 mb-3">
              <Library className="w-5 h-5 text-muted-foreground" />
              <div>
                <h3 className="font-semibold">Comic Library Scan</h3>
                <p className="text-sm text-muted-foreground">
                  Scan your comic directory to find unmatched files
                </p>
              </div>
            </div>
            <Button
              onClick={handleRefreshImport}
              disabled={refreshImportMutation.isPending}
              className="w-full"
            >
              <RefreshCw
                className={`w-4 h-4 mr-2 ${refreshImportMutation.isPending ? "animate-spin" : ""}`}
              />
              Scan Comic Library
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5">
            <div className="flex items-center gap-3 mb-3">
              <BookOpen className="w-5 h-5 text-muted-foreground" />
              <div>
                <h3 className="font-semibold">Manga Library Scan</h3>
                <p className="text-sm text-muted-foreground">
                  {mangaDirConfigured
                    ? "Scan your manga directory to import existing collections"
                    : "Configure a Manga Directory in Settings to enable"}
                </p>
              </div>
            </div>
            <Button
              onClick={handleMangaScan}
              disabled={
                !mangaDirConfigured ||
                mangaScanMutation.isPending ||
                mangaScanning
              }
              className="w-full"
            >
              <RefreshCw
                className={`w-4 h-4 mr-2 ${mangaScanning ? "animate-spin" : ""}`}
              />
              Scan Manga Library
            </Button>
            {mangaScanning && mangaProgress?.progress && (
              <div className="mt-3 text-sm text-muted-foreground space-y-1">
                <p>
                  Series found: {mangaProgress.progress.series_found} | Matched:{" "}
                  {mangaProgress.progress.series_matched} | Imported:{" "}
                  {mangaProgress.progress.series_imported}
                </p>
                {mangaProgress.progress.current_series && (
                  <p>Processing: {mangaProgress.progress.current_series}</p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="flex items-center mb-4">
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
