import { Inbox, RefreshCw, FolderOpen } from "lucide-react";
import { useRefreshImport } from "@/hooks/useImport";
import { useConfig } from "@/hooks/useConfig";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

export default function ImportInboxSection() {
  const { data: appConfig } = useConfig();
  const importDir = appConfig?.import_dir as string | undefined;
  const refreshImportMutation = useRefreshImport();
  const { addToast } = useToast();

  const handleScanNow = async () => {
    try {
      await refreshImportMutation.mutateAsync();
      addToast({
        type: "info",
        message: "Import inbox scan started.",
      });
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to start inbox scan: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-foreground">Import Inbox</h2>
        <p className="text-sm text-muted-foreground">
          Monitor a directory for new files to auto-match against your library
        </p>
      </div>

      <Card>
        <CardContent className="p-5">
          <div className="flex items-center gap-3 mb-3">
            <Inbox className="w-5 h-5 text-muted-foreground" />
            <div className="flex-1">
              <h3 className="font-semibold">Import Directory</h3>
              {importDir ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <FolderOpen className="w-3.5 h-3.5" />
                  <span className="font-mono text-xs">{importDir}</span>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Not configured. Set an Import Directory in your config.ini to
                  enable auto-importing.
                </p>
              )}
            </div>
          </div>
          <Button
            onClick={handleScanNow}
            disabled={!importDir || refreshImportMutation.isPending}
            className="w-full"
          >
            <RefreshCw
              className={`w-4 h-4 mr-2 ${refreshImportMutation.isPending ? "animate-spin" : ""}`}
            />
            Scan Now
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
