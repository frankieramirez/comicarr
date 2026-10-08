import { Inbox, RefreshCw, FolderOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useRefreshImport } from "@/hooks/useImport";
import { useConfig } from "@/hooks/useConfig";
import { useToast } from "@/components/ui/toast";

export default function ImportInboxSection() {
  const { data: appConfig } = useConfig();
  const importDir = appConfig?.import_dir as string | undefined;
  const refreshImportMutation = useRefreshImport();
  const { addToast } = useToast();

  const handleScanNow = async () => {
    try {
      await refreshImportMutation.mutateAsync();
      addToast({ type: "info", message: "Import inbox scan started." });
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to start inbox scan: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const configured = !!importDir;
  const busy = refreshImportMutation.isPending;

  return (
    <div
      className="rounded-lg border px-3.5 py-3"
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
          <Inbox className="w-3.5 h-3.5" strokeWidth={1.75} />
        </div>

        <div className="flex-1 min-w-0">
          <div className="text-[13px] font-medium leading-tight">
            Import directory
          </div>
          {configured ? (
            <div className="flex items-center gap-1.5 mt-0.5 font-mono text-[10.5px] text-muted-foreground truncate">
              <FolderOpen className="w-3 h-3 shrink-0" strokeWidth={1.75} />
              <span className="truncate">{importDir}</span>
            </div>
          ) : (
            <div className="text-[11px] text-muted-foreground mt-0.5">
              Set an Import Directory in your config.ini to enable
              auto-importing.
            </div>
          )}
        </div>

        {configured ? (
          <Button
            type="button"
            variant="outline"
            size="compact"
            onClick={handleScanNow}
            disabled={busy}
            className="shrink-0"
          >
            <RefreshCw
              className={busy ? "animate-spin" : ""}
              style={{
                color: busy ? "var(--primary)" : "var(--muted-foreground)",
              }}
              strokeWidth={2}
            />
            <span>{busy ? "scanning" : "scan now"}</span>
          </Button>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="compact"
            mono
            disabled
            className="shrink-0 text-muted-foreground"
          >
            <span>not set</span>
          </Button>
        )}
      </div>
    </div>
  );
}
