import { useState, useEffect } from "react";
import { RefreshCw, Library, BookOpen } from "lucide-react";
import {
  useComicScan,
  useComicScanProgress,
  useComicScanConfirm,
  useMangaScan,
  useMangaScanProgress,
  useMangaScanConfirm,
} from "@/hooks/useImport";
import { useConfig } from "@/hooks/useConfig";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import LibraryScanResults from "./LibraryScanResults";

export default function LibraryScanSection() {
  const { data: appConfig } = useConfig();
  const comicDirConfigured = !!appConfig?.comic_dir;
  const mangaDirConfigured = !!appConfig?.manga_dir;
  const { addToast } = useToast();

  // Comic scan state
  const comicScanMutation = useComicScan();
  const [comicScanning, setComicScanning] = useState(false);
  const { data: comicProgress } = useComicScanProgress(comicScanning);
  const comicConfirmMutation = useComicScanConfirm();

  // Manga scan state
  const mangaScanMutation = useMangaScan();
  const [mangaScanning, setMangaScanning] = useState(false);
  const { data: mangaProgress } = useMangaScanProgress(mangaScanning);
  const mangaConfirmMutation = useMangaScanConfirm();

  // Comic scan terminal state
  const comicStatus = comicProgress?.status;
  const comicTerminal =
    comicScanning && (comicStatus === "completed" || comicStatus === "error");
  useEffect(() => {
    if (!comicTerminal) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Sync polling state with server-driven terminal status
    setComicScanning(false);
    if (comicStatus === "error") {
      addToast({ type: "error", message: "Comic scan failed" });
    }
  }, [comicTerminal, comicStatus, addToast]);

  // Manga scan terminal state
  const mangaStatus = mangaProgress?.status;
  const mangaTerminal =
    mangaScanning && (mangaStatus === "completed" || mangaStatus === "error");
  useEffect(() => {
    if (!mangaTerminal) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Sync polling state with server-driven terminal status
    setMangaScanning(false);
    if (mangaStatus === "error") {
      addToast({ type: "error", message: "Manga scan failed" });
    }
  }, [mangaTerminal, mangaStatus, addToast]);

  const handleComicScan = async () => {
    try {
      await comicScanMutation.mutateAsync();
      setComicScanning(true);
      addToast({
        type: "info",
        message: "Comic library scan started.",
      });
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to start comic scan: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleMangaScan = async () => {
    try {
      await mangaScanMutation.mutateAsync();
      setMangaScanning(true);
      addToast({
        type: "info",
        message: "Manga library scan started.",
      });
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to start manga scan: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleComicConfirm = async (scanId: string, selectedIds: string[]) => {
    try {
      const result = await comicConfirmMutation.mutateAsync({
        scanId,
        selectedIds,
      });
      addToast({
        type: "success",
        message: `Imported ${result.imported} comic series`,
      });
    } catch (err) {
      addToast({
        type: "error",
        message: `Import failed: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleMangaConfirm = async (scanId: string, selectedIds: string[]) => {
    try {
      const result = await mangaConfirmMutation.mutateAsync({
        scanId,
        selectedIds,
      });
      addToast({
        type: "success",
        message: `Imported ${result.imported} manga series`,
      });
    } catch (err) {
      addToast({
        type: "error",
        message: `Import failed: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const comicResults = comicProgress?.results;
  const comicScanId = comicProgress?.scan_id;
  const mangaResults = mangaProgress?.results;
  const mangaScanId = mangaProgress?.scan_id;

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-foreground">Library Scan</h2>
        <p className="text-sm text-muted-foreground">
          Scan your existing directories to find and import series
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardContent className="p-5">
            <div className="flex items-center gap-3 mb-3">
              <Library className="w-5 h-5 text-muted-foreground" />
              <div>
                <h3 className="font-semibold">Comic Library</h3>
                <p className="text-sm text-muted-foreground">
                  {comicDirConfigured
                    ? "Scan your comic directory and select series to import"
                    : "Configure a Comic Directory in Settings to enable"}
                </p>
              </div>
            </div>
            <Button
              onClick={handleComicScan}
              disabled={
                !comicDirConfigured ||
                comicScanMutation.isPending ||
                comicScanning
              }
              className="w-full"
            >
              <RefreshCw
                className={`w-4 h-4 mr-2 ${comicScanning ? "animate-spin" : ""}`}
              />
              Scan Comic Library
            </Button>
            {comicScanning && comicProgress?.progress && (
              <div className="mt-3 text-sm text-muted-foreground space-y-1">
                <p>
                  Series found: {comicProgress.progress.series_found} | Matched:{" "}
                  {comicProgress.progress.series_matched}
                </p>
                {comicProgress.progress.current_series && (
                  <p>Processing: {comicProgress.progress.current_series}</p>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5">
            <div className="flex items-center gap-3 mb-3">
              <BookOpen className="w-5 h-5 text-muted-foreground" />
              <div>
                <h3 className="font-semibold">Manga Library</h3>
                <p className="text-sm text-muted-foreground">
                  {mangaDirConfigured
                    ? "Scan your manga directory and select series to import"
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
                  {mangaProgress.progress.series_matched}
                </p>
                {mangaProgress.progress.current_series && (
                  <p>Processing: {mangaProgress.progress.current_series}</p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {comicResults && comicResults.length > 0 && comicScanId && (
        <LibraryScanResults
          results={comicResults}
          scanId={comicScanId}
          onConfirm={handleComicConfirm}
          isConfirming={comicConfirmMutation.isPending}
          type="comic"
        />
      )}

      {mangaResults && mangaResults.length > 0 && mangaScanId && (
        <LibraryScanResults
          results={mangaResults}
          scanId={mangaScanId}
          onConfirm={handleMangaConfirm}
          isConfirming={mangaConfirmMutation.isPending}
          type="manga"
        />
      )}
    </div>
  );
}
