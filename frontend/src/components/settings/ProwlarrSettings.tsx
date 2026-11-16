import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
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
  usenet_indexers?: number;
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

function indexerCount(count: number, kind: string): string {
  return count === 1
    ? t`1 enabled ${kind} indexer`
    : t`${count} enabled ${kind} indexers`;
}

function resultMessage(result: ProwlarrTestResult): string {
  if (!result.success) return result.error || t`Connection test failed`;
  const torrents = indexerCount(result.torrent_indexers ?? 0, "torrent");
  const usenet = indexerCount(result.usenet_indexers ?? 0, t`Usenet`);
  return t`Connected. Prowlarr has ${torrents} and ${usenet}.`;
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
        error: err instanceof Error ? err.message : t`Connection test failed`,
      });
    } finally {
      setIsTesting(false);
    }
  };

  return (
    <SettingGroup
      title={t`Prowlarr`}
      description={t`Search every indexer in Prowlarr with one request. Prowlarr skips indexers it knows are failing and counts Comicarr's searches toward each indexer's limits.`}
    >
      <SettingField
        label={t`Search with Prowlarr`}
        type="checkbox"
        checked={enabled}
        onChange={(value) => onChange("enable_prowlarr", value as boolean)}
        helpText={t`Torrent results come from a provider named Prowlarr. You can remove the separate Torznab indexers you copied from it.`}
      />
      {enabled && (
        <SettingField
          label={t`Include Usenet indexers`}
          type="checkbox"
          checked={Boolean(formData.prowlarr_usenet)}
          onChange={(value) => onChange("prowlarr_usenet", value as boolean)}
          helpText={t`Usenet results come from a provider named Prowlarr (Usenet) and go to your Usenet download client. Turn this on only if you remove the same indexers from Usenet indexers below, or each search hits them twice.`}
        />
      )}
      {enabled &&
        !formData.prowlarr_usenet &&
        config.enable_torrent_search === false && (
          <Callout tone="warning" className="text-[12px]">
            <Trans>
              Torrent search is off and Usenet indexers are not included, so
              Prowlarr won't be searched. Turn on Include Usenet indexers, or
              set enable_torrent_search under [Torrents] in the config file
              shown in the Settings header.
            </Trans>
          </Callout>
        )}
      <SettingField
        label={t`Prowlarr URL`}
        value={host}
        onChange={(value) => onChange("prowlarr_host", value as string)}
        placeholder="http://prowlarr:9696"
        helpText={t`The address Comicarr can reach, including the port and any URL base.`}
      />
      <SettingField
        label={t`Prowlarr API key`}
        type="password"
        value={apiKey}
        onChange={(value) => onChange("prowlarr_apikey", value as string)}
        placeholder={
          config.prowlarr_apikey_set
            ? t`API key saved (enter a new value to change)`
            : t`Settings → General → API Key in Prowlarr`
        }
        helpText={t`Stored encrypted and never returned by the API.`}
      />
      <SettingField
        label={t`Prowlarr categories`}
        value={formData.prowlarr_categories ?? ""}
        onChange={(value) => onChange("prowlarr_categories", value as string)}
        placeholder="7030"
        helpText={t`Newznab category numbers, separated by commas. 7030 is comics; add 7010 for magazines.`}
      />
      <SettingField
        label={t`Verify Prowlarr TLS certificate`}
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
              <Trans>Testing...</Trans>
            </>
          ) : (
            <>
              <Zap className="h-4 w-4 mr-2" />
              <Trans>Test Connection</Trans>
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
