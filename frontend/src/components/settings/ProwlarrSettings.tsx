import { useState } from "react";
import { CheckCircle2, Loader2, XCircle, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { apiRequest } from "@/lib/api";
import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";
import type {
  ReadableConfig,
  SettingsFormData,
  WritableConfig,
} from "../../types/config.generated";

interface ProwlarrTestResult {
  success: boolean;
  torrent_indexers?: number;
  error?: string;
}

interface ProwlarrSettingsProps {
  config: ReadableConfig;
  formData: SettingsFormData;
  onChange: <K extends keyof WritableConfig>(
    key: K,
    value: NonNullable<WritableConfig[K]>,
  ) => void;
}

function resultMessage(result: ProwlarrTestResult): string {
  if (!result.success) return result.error || "Connection test failed";
  const count = result.torrent_indexers ?? 0;
  return count === 1
    ? "Connected. Prowlarr has 1 enabled torrent indexer."
    : `Connected. Prowlarr has ${count} enabled torrent indexers.`;
}

export function ProwlarrSettings({
  config,
  formData,
  onChange,
}: ProwlarrSettingsProps) {
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<ProwlarrTestResult | null>(null);

  const enabled = Boolean(formData.enable_prowlarr);
  const host = formData.prowlarr_host ?? "";
  const apiKey = formData.prowlarr_apikey ?? "";
  const canTest =
    host.trim().length > 0 &&
    (apiKey.length > 0 || Boolean(config.prowlarr_apikey_set));

  const handleTest = async () => {
    setIsTesting(true);
    setTestResult(null);
    try {
      setTestResult(
        await apiRequest<ProwlarrTestResult>(
          "POST",
          "/api/config/prowlarr/test",
          {
            host,
            api_key: apiKey,
            verify: formData.prowlarr_verify ?? true,
          },
        ),
      );
    } catch (err) {
      setTestResult({
        success: false,
        error: err instanceof Error ? err.message : "Connection test failed",
      });
    } finally {
      setIsTesting(false);
    }
  };

  return (
    <SettingGroup
      title="Prowlarr"
      description="Search every torrent indexer in Prowlarr with one request. Prowlarr skips indexers it knows are failing."
    >
      <SettingField
        label="Search with Prowlarr"
        type="checkbox"
        checked={enabled}
        onChange={(value) => onChange("enable_prowlarr", value as boolean)}
        helpText="Prowlarr appears as one provider named Prowlarr. You can remove the separate Torznab indexers you copied from it."
      />
      {enabled && config.enable_torrent_search === false && (
        <Callout tone="warning" className="text-[12px]">
          Torrent search is off, so Prowlarr won't be searched. Set
          enable_torrent_search under [Torrents] in the config file shown in the
          Settings header.
        </Callout>
      )}
      <SettingField
        label="Prowlarr URL"
        value={host}
        onChange={(value) => onChange("prowlarr_host", value as string)}
        placeholder="http://prowlarr:9696"
        helpText="The address Comicarr can reach, including the port and any URL base."
      />
      <SettingField
        label="Prowlarr API key"
        type="password"
        value={apiKey}
        onChange={(value) => onChange("prowlarr_apikey", value as string)}
        placeholder={
          config.prowlarr_apikey_set
            ? "API key saved (enter a new value to change)"
            : "Settings → General → API Key in Prowlarr"
        }
        helpText="Stored encrypted and never returned by the API."
      />
      <SettingField
        label="Prowlarr categories"
        value={formData.prowlarr_categories ?? ""}
        onChange={(value) => onChange("prowlarr_categories", value as string)}
        placeholder="7030"
        helpText="Newznab category numbers, separated by commas. 7030 is comics; add 7010 for magazines."
      />
      <SettingField
        label="Verify Prowlarr TLS certificate"
        type="checkbox"
        checked={formData.prowlarr_verify ?? true}
        onChange={(value) => onChange("prowlarr_verify", value as boolean)}
      />
      <div className="flex flex-wrap items-center gap-3 pt-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleTest}
          disabled={!canTest || isTesting}
        >
          {isTesting ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Testing...
            </>
          ) : (
            <>
              <Zap className="h-4 w-4 mr-2" />
              Test Connection
            </>
          )}
        </Button>
        {testResult && (
          <p
            role={testResult.success ? "status" : "alert"}
            className="flex items-center gap-2 text-[12px]"
          >
            {testResult.success ? (
              <CheckCircle2 className="h-4 w-4 text-[var(--status-active)]" />
            ) : (
              <XCircle className="h-4 w-4 text-[var(--status-error)]" />
            )}
            {resultMessage(testResult)}
          </p>
        )}
      </div>
    </SettingGroup>
  );
}
