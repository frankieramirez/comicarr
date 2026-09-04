import { useState } from "react";
import {
  RefreshCw,
  Library,
  BookOpen,
  FolderOpen,
  Loader2,
  type LucideIcon,
} from "lucide-react";
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
import LibraryScanResults from "./LibraryScanResults";

export default function LibraryScanSection() {
  const { data: appConfig } = useConfig();
  const comicDir = appConfig?.comic_dir as string | undefined;
  const mangaDir = appConfig?.manga_dir as string | undefined;
  const { addToast } = useToast();

  const comicScanMutation = useComicScan();
  const { data: comicProgress } = useComicScanProgress();
  const comicConfirmMutation = useComicScanConfirm();
  const [comicImported, setComicImported] = useState<number | null>(null);

  const mangaScanMutation = useMangaScan();
  const { data: mangaProgress } = useMangaScanProgress();
  const mangaConfirmMutation = useMangaScanConfirm();
  const [mangaImported, setMangaImported] = useState<number | null>(null);
  const comicScanning = comicProgress?.status === "scanning";
  const mangaScanning = mangaProgress?.status === "scanning";

  const handleComicScan = async () => {
    try {
      await comicScanMutation.mutateAsync();
      setComicImported(null);
      addToast({ type: "info", message: "Comic library scan started." });
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
      setMangaImported(null);
      addToast({ type: "info", message: "Manga library scan started." });
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
      setComicImported(result.imported);
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
      setMangaImported(result.imported);
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
    <div className="space-y-3">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-2.5">
        <ScanTile
          icon={Library}
          label="Comic library"
          path={comicDir}
          notConfiguredHint="Set Comic Directory in Settings → Media"
          busy={comicScanMutation.isPending || comicScanning}
          onScan={handleComicScan}
          progress={
            comicScanning
              ? {
                  found: comicProgress?.progress?.series_found,
                  matched: comicProgress?.progress?.series_matched,
                  current: comicProgress?.progress?.current_series,
                }
              : undefined
          }
        />
        <ScanTile
          icon={BookOpen}
          label="Manga library"
          path={mangaDir}
          notConfiguredHint="Set Manga Directory in Settings → Media"
          busy={mangaScanMutation.isPending || mangaScanning}
          onScan={handleMangaScan}
          progress={
            mangaScanning
              ? {
                  found: mangaProgress?.progress?.series_found,
                  matched: mangaProgress?.progress?.series_matched,
                  current: mangaProgress?.progress?.current_series,
                }
              : undefined
          }
        />
      </div>

      <ScanFailure type="comic" progress={comicProgress} />
      <ScanFailure type="manga" progress={mangaProgress} />
      <ImportSummary type="comic" imported={comicImported} />
      <ImportSummary type="manga" imported={mangaImported} />

      {comicImported === null &&
        comicResults &&
        comicResults.length > 0 &&
        comicScanId && (
          <LibraryScanResults
            results={comicResults}
            scanId={comicScanId}
            onConfirm={handleComicConfirm}
            isConfirming={comicConfirmMutation.isPending}
            type="comic"
          />
        )}

      {mangaImported === null &&
        mangaResults &&
        mangaResults.length > 0 &&
        mangaScanId && (
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

function ScanFailure({
  type,
  progress,
}: {
  type: "comic" | "manga";
  progress?: {
    status: string | null;
    progress: { errors: string[] };
  };
}) {
  if (progress?.status !== "error") return null;

  const detail = progress.progress.errors[0];
  return (
    <div
      className="rounded-[6px] border border-destructive/40 bg-destructive/10 px-3.5 py-3 text-[12px] text-foreground"
      role="alert"
    >
      {type === "comic" ? "Comic" : "Manga"} library scan failed
      {detail ? `: ${detail}` : "."}
    </div>
  );
}

function ImportSummary({
  type,
  imported,
}: {
  type: "comic" | "manga";
  imported: number | null;
}) {
  if (imported === null) return null;

  return (
    <div
      className="rounded-[6px] border border-[var(--status-active)]/40 bg-[var(--status-active)]/10 px-3.5 py-3 text-[12px] text-foreground"
      role="status"
    >
      Imported {imported} {type} series. The library has been refreshed.
    </div>
  );
}

interface ScanTileProps {
  icon: LucideIcon;
  label: string;
  path?: string;
  notConfiguredHint: string;
  busy: boolean;
  onScan: () => void;
  progress?: {
    found?: number;
    matched?: number;
    current?: string | null;
  };
}

function ScanTile({
  icon: Icon,
  label,
  path,
  notConfiguredHint,
  busy,
  onScan,
  progress,
}: ScanTileProps) {
  const configured = !!path;

  return (
    <div
      className="rounded-[6px] border px-3.5 py-3"
      style={{ borderColor: "var(--border)", background: "var(--card)" }}
    >
      <div className="flex items-center gap-3">
        <div
          className="w-7 h-7 rounded-[5px] grid place-items-center shrink-0"
          style={{
            background: "var(--secondary)",
            color: "var(--muted-foreground)",
          }}
        >
          <Icon className="w-3.5 h-3.5" strokeWidth={1.75} />
        </div>

        <div className="flex-1 min-w-0">
          <div className="text-[13px] font-medium leading-tight">{label}</div>
          {configured ? (
            <div className="flex items-center gap-1.5 mt-0.5 font-mono text-[10.5px] text-muted-foreground truncate">
              <FolderOpen className="w-3 h-3 shrink-0" strokeWidth={1.75} />
              <span className="truncate">{path}</span>
            </div>
          ) : (
            <div className="text-[11px] text-muted-foreground mt-0.5">
              {notConfiguredHint}
            </div>
          )}
        </div>

        <ScanButton configured={configured} busy={busy} onClick={onScan} />
      </div>

      {progress && (
        <div
          className="mt-3 pt-2.5 border-t font-mono text-[11px] text-muted-foreground flex items-center gap-3"
          style={{ borderColor: "var(--border)" }}
        >
          <Loader2
            className="w-3 h-3 animate-spin shrink-0"
            style={{ color: "var(--primary)" }}
          />
          <span>
            found <span className="text-foreground">{progress.found ?? 0}</span>{" "}
            · matched{" "}
            <span className="text-foreground">{progress.matched ?? 0}</span>
          </span>
          {progress.current && (
            <span
              className="truncate ml-auto"
              style={{ color: "var(--text-muted)" }}
            >
              {progress.current}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function ScanButton({
  configured,
  busy,
  onClick,
}: {
  configured: boolean;
  busy: boolean;
  onClick: () => void;
}) {
  if (!configured) {
    return (
      <button
        type="button"
        disabled
        className="inline-flex items-center gap-1.5 px-2.5 h-7 rounded-[5px] border font-mono text-[10.5px] tracking-[0.05em] uppercase shrink-0 disabled:opacity-60 disabled:cursor-not-allowed"
        style={{
          borderColor: "var(--border)",
          color: "var(--muted-foreground)",
        }}
      >
        <span>not set</span>
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className="inline-flex items-center gap-1.5 px-2.5 h-7 rounded-[5px] border text-[11.5px] font-medium shrink-0 hover:bg-secondary transition-colors disabled:opacity-70"
      style={{
        borderColor: "var(--border)",
        color: "var(--foreground)",
      }}
    >
      <RefreshCw
        className={`w-3 h-3 ${busy ? "animate-spin" : ""}`}
        style={{ color: busy ? "var(--primary)" : "var(--muted-foreground)" }}
        strokeWidth={2}
      />
      <span>{busy ? "scanning" : "scan"}</span>
    </button>
  );
}
