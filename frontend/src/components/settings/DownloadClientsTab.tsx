import { SettingGroup } from "./SettingGroup";
import { AlertCircle } from "lucide-react";

interface DownloadClientsTabProps {
  config: Record<string, unknown>;
}

export function DownloadClientsTab({ config }: DownloadClientsTabProps) {
  return (
    <div className="space-y-6">
      <SettingGroup
        title="Download Clients"
        description="Currently configured download clients (read-only)"
      >
        <div className="space-y-4">
          <div className="bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
            <div className="flex items-start space-x-3">
              <AlertCircle className="h-5 w-5 text-blue-600 dark:text-blue-400 mt-0.5" />
              <div>
                <h4 className="text-sm font-semibold text-blue-900 dark:text-blue-100 mb-1">
                  Current Configuration
                </h4>
                <div className="text-sm text-blue-800 dark:text-blue-200 space-y-2">
                  <p>
                    <span className="font-medium">NZB Client:</span>{" "}
                    {(config.nzb_downloader_label as string) ||
                      "Not configured"}
                  </p>
                  <p>
                    <span className="font-medium">Torrent Client:</span>{" "}
                    {(config.torrent_downloader_label as string) ||
                      "Not configured"}
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-background border border-card-border rounded-lg p-4">
            <div className="flex items-start space-x-3">
              <AlertCircle className="h-5 w-5 text-muted-foreground mt-0.5" />
              <div>
                <h4 className="text-sm font-semibold text-foreground mb-1">
                  Advanced Configuration Coming Soon
                </h4>
                <p className="text-sm text-muted-foreground">
                  Full download client configuration (SABnzbd, NZBGet,
                  qBittorrent, etc.) will be available in a future update. For
                  now, please configure these settings in your config.ini file
                  or through the classic web interface.
                </p>
              </div>
            </div>
          </div>
        </div>
      </SettingGroup>
    </div>
  );
}
