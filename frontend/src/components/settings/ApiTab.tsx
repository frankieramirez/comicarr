import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { Copy, RefreshCw } from "lucide-react";
import { useGenerateApiKey } from "@/hooks/useConfig";

import type {
  ReadableConfig,
  SettingsFormData,
  WritableConfig,
} from "../../types/config.generated";

// A language code example, the same in every language.
const LANGUAGE_CODE_EXAMPLE = "en";

interface ApiTabProps {
  config: ReadableConfig;
  formData: SettingsFormData;
  onChange: <K extends keyof WritableConfig>(
    key: K,
    value: NonNullable<WritableConfig[K]>,
  ) => void;
  /** Refusals keyed by field, shown under the field. */
  errors?: Record<string, string>;
  regeneratedApiKey: string | null;
  onRegeneratedApiKey: (apiKey: string) => void;
}

export function ApiTab({
  config,
  formData,
  onChange,
  errors,
  regeneratedApiKey,
  onRegeneratedApiKey,
}: ApiTabProps) {
  const { addToast } = useToast();
  const generateApiKey = useGenerateApiKey();
  const displayedApiKey = regeneratedApiKey || "";
  const apiKeyIsSet = config.api_key_set || false;
  const comicvineApiIsSet = config.comicvine_api_set || false;
  const metronPasswordIsSet = config.metron_password_set || false;
  // The saved value, not the form draft: the note is about what is live.
  const mcpEnabled = config.mcp_enabled || false;

  const handleCopyApiKey = async () => {
    if (!displayedApiKey) {
      addToast({
        type: "error",
        message: t`Regenerate the API key before copying it.`,
      });
      return;
    }

    try {
      await navigator.clipboard.writeText(displayedApiKey);
      addToast({
        type: "success",
        message: t`API key copied to clipboard`,
      });
    } catch {
      addToast({
        type: "error",
        message: t`Failed to copy API key`,
      });
    }
  };

  const handleRegenerateApiKey = async () => {
    if (
      !confirm(
        mcpEnabled
          ? t`Are you sure you want to regenerate the API key? This will invalidate any existing API integrations and disconnect every MCP agent.`
          : t`Are you sure you want to regenerate the API key? This will invalidate any existing API integrations.`,
      )
    ) {
      return;
    }

    try {
      const newApiKey = await generateApiKey.mutateAsync();
      onRegeneratedApiKey(newApiKey);
      addToast({
        type: "success",
        message: t`API key regenerated.`,
      });
    } catch {
      addToast({
        type: "error",
        message: t`Failed to regenerate API key`,
      });
    }
  };

  const comicvineEnabled = formData.comicvine_enabled ?? true;
  const mangadexEnabled = formData.mangadex_enabled ?? false;

  return (
    <div className="space-y-6">
      <SettingGroup
        title={t`Comicarr API Key`}
        description={t`This key is used to authenticate API requests to Comicarr`}
      >
        <div className="space-y-2">
          <label htmlFor="settings-api-key" className="text-sm font-medium">
            <Trans>API Key</Trans>
          </label>
          <div className="flex space-x-2">
            <input
              id="settings-api-key"
              type="text"
              value={displayedApiKey}
              placeholder={
                apiKeyIsSet
                  ? t`Configured - regenerate to view a new key`
                  : t`No API key configured`
              }
              readOnly
              className="flex-1 px-3 py-2 border border-input rounded-md bg-background font-mono text-sm"
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={handleCopyApiKey}
              disabled={!displayedApiKey}
              title={t`Copy to clipboard`}
              aria-label={t`Copy API key`}
            >
              <Copy className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={handleRegenerateApiKey}
              disabled={generateApiKey.isPending}
              title={t`Regenerate API key`}
              aria-label={t`Regenerate API key`}
            >
              <RefreshCw
                className={`h-4 w-4 ${generateApiKey.isPending ? "animate-spin" : ""}`}
              />
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            <Trans>Use this key in API requests and integrations</Trans>
          </p>
          {mcpEnabled && (
            <p
              data-testid="mcp-rotation-note"
              className="text-xs text-foreground-2"
            >
              <Trans>
                MCP is on. Regenerating this key disconnects every connected MCP
                agent at once; each one needs the new key.
              </Trans>
            </p>
          )}
        </div>
      </SettingGroup>

      {comicvineEnabled && (
        <SettingGroup
          title={t`Comic Vine`}
          description={t`Configure Comic Vine integration for metadata`}
        >
          <SettingField
            label={t`Comic Vine API Key`}
            value={formData.comicvine_api || ""}
            type="password"
            onChange={(value) => onChange("comicvine_api", value as string)}
            placeholder={
              comicvineApiIsSet
                ? t`Key saved (enter new value to change)`
                : t`Enter your 40-character Comic Vine API key`
            }
            helpText={
              comicvineApiIsSet && !formData.comicvine_api
                ? t`Comic Vine API key is configured. Enter a new value to change it.`
                : t`Get your API key from https://comicvine.gamespot.com/api/`
            }
          />
          <SettingField
            label={t`Verify SSL`}
            type="checkbox"
            checked={formData.cv_verify}
            onChange={(checked) => onChange("cv_verify", checked as boolean)}
            helpText={t`Verify SSL certificates when connecting to Comic Vine`}
          />
          <SettingField
            label={t`Comic Vine Only`}
            type="checkbox"
            checked={formData.cv_only}
            onChange={(checked) => onChange("cv_only", checked as boolean)}
            helpText={t`Use only Comic Vine for metadata (ignore local cache)`}
          />
        </SettingGroup>
      )}

      {comicvineEnabled && (
        <SettingGroup
          title={t`Metron`}
          description={t`Use Metron API for comic search (fixes sorting issues)`}
        >
          <SettingField
            label={t`Use Metron for Search`}
            type="checkbox"
            checked={formData.use_metron_search}
            onChange={(checked) =>
              onChange("use_metron_search", checked as boolean)
            }
            helpText={t`Use Metron API instead of Comic Vine for search results`}
          />
          <SettingField
            label={t`Metron Username`}
            value={formData.metron_username}
            type="text"
            onChange={(value) => onChange("metron_username", value as string)}
            placeholder={t`Your Metron username`}
            helpText={t`Register at https://metron.cloud`}
          />
          <SettingField
            label={t`Metron Password`}
            value={formData.metron_password}
            type="password"
            onChange={(value) => onChange("metron_password", value as string)}
            placeholder={
              metronPasswordIsSet
                ? t`Password saved (enter new value to change)`
                : t`Your Metron password`
            }
            helpText={
              metronPasswordIsSet && !formData.metron_password
                ? t`Metron password is configured. Enter a new value to change it.`
                : t`Register at https://metron.cloud`
            }
          />
        </SettingGroup>
      )}

      <SettingGroup
        title={t`MyAnimeList`}
        description={t`Use MAL as primary manga metadata source for better search coverage`}
      >
        <SettingField
          label={t`Enable MAL`}
          type="checkbox"
          checked={formData.mal_enabled}
          onChange={(checked) => onChange("mal_enabled", checked as boolean)}
          helpText={t`Use MyAnimeList for manga search and metadata (MangaDex still provides chapter data)`}
        />
        <SettingField
          label={t`MAL Client ID`}
          value={formData.mal_client_id}
          type="password"
          onChange={(value) => onChange("mal_client_id", value as string)}
          placeholder={t`Your MAL API Client ID`}
          helpText={t`Get your Client ID from https://myanimelist.net/apiconfig`}
        />
      </SettingGroup>

      {mangadexEnabled && (
        <SettingGroup
          title={t`MangaDex`}
          description={t`Configure MangaDex integration for chapter data`}
        >
          <SettingField
            label={t`Languages`}
            value={formData.mangadex_languages}
            type="text"
            onChange={(value) =>
              onChange("mangadex_languages", value as string)
            }
            placeholder={LANGUAGE_CODE_EXAMPLE}
            helpText={t`Comma-separated language codes (e.g., en,ja)`}
            error={errors?.mangadex_languages}
          />
          <SettingField
            label={t`Content Rating`}
            value={formData.mangadex_content_rating}
            type="text"
            onChange={(value) =>
              onChange("mangadex_content_rating", value as string)
            }
            placeholder="safe,suggestive"
            helpText={t`Comma-separated ratings: safe, suggestive, erotica, pornographic`}
            error={errors?.mangadex_content_rating}
          />
        </SettingGroup>
      )}
    </div>
  );
}
