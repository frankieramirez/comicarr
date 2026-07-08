import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { Copy, RefreshCw } from "lucide-react";
import { useGenerateApiKey } from "@/hooks/useConfig";

interface ApiTabProps {
  config: Record<string, unknown>;
  formData: Record<string, unknown>;
  onChange: (key: string, value: string | boolean) => void;
  regeneratedApiKey: string | null;
  onRegeneratedApiKey: (apiKey: string) => void;
}

export function ApiTab({
  config,
  formData,
  onChange,
  regeneratedApiKey,
  onRegeneratedApiKey,
}: ApiTabProps) {
  const { addToast } = useToast();
  const generateApiKey = useGenerateApiKey();
  const displayedApiKey = regeneratedApiKey || "";
  const apiKeyIsSet = (config.api_key_set as boolean) || false;
  const comicvineApiIsSet = (config.comicvine_api_set as boolean) || false;
  const metronPasswordIsSet = (config.metron_password_set as boolean) || false;

  const handleCopyApiKey = async () => {
    if (!displayedApiKey) {
      addToast({
        type: "error",
        message: "Regenerate the API key before copying it.",
      });
      return;
    }

    try {
      await navigator.clipboard.writeText(displayedApiKey);
      addToast({
        type: "success",
        message: "API key copied to clipboard",
      });
    } catch {
      addToast({
        type: "error",
        message: "Failed to copy API key",
      });
    }
  };

  const handleRegenerateApiKey = async () => {
    if (
      !confirm(
        "Are you sure you want to regenerate the API key? This will invalidate any existing API integrations.",
      )
    ) {
      return;
    }

    try {
      const newApiKey = await generateApiKey.mutateAsync();
      onRegeneratedApiKey(newApiKey);
      addToast({
        type: "success",
        message: "API key regenerated.",
      });
    } catch {
      addToast({
        type: "error",
        message: "Failed to regenerate API key",
      });
    }
  };

  const comicvineEnabled = (formData.comicvine_enabled as boolean) ?? true;
  const mangadexEnabled = (formData.mangadex_enabled as boolean) ?? false;

  return (
    <div className="space-y-6">
      <SettingGroup
        title="Comicarr API Key"
        description="This key is used to authenticate API requests to Comicarr"
      >
        <div className="space-y-2">
          <label className="text-sm font-medium">API Key</label>
          <div className="flex space-x-2">
            <input
              type="text"
              value={displayedApiKey}
              placeholder={
                apiKeyIsSet
                  ? "Configured - regenerate to view a new key"
                  : "No API key configured"
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
              title="Copy to clipboard"
            >
              <Copy className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={handleRegenerateApiKey}
              disabled={generateApiKey.isPending}
              title="Regenerate API key"
            >
              <RefreshCw
                className={`h-4 w-4 ${generateApiKey.isPending ? "animate-spin" : ""}`}
              />
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Use this key in API requests and integrations
          </p>
        </div>
      </SettingGroup>

      {comicvineEnabled && (
        <SettingGroup
          title="Comic Vine"
          description="Configure Comic Vine integration for metadata"
        >
          <SettingField
            label="Comic Vine API Key"
            value={(formData.comicvine_api as string | undefined) || ""}
            type="password"
            onChange={(value) => onChange("comicvine_api", value as string)}
            placeholder={
              comicvineApiIsSet
                ? "Key saved (enter new value to change)"
                : "Enter your 40-character Comic Vine API key"
            }
            helpText={
              comicvineApiIsSet && !formData.comicvine_api
                ? "Comic Vine API key is configured. Enter a new value to change it."
                : "Get your API key from https://comicvine.gamespot.com/api/"
            }
          />
          <SettingField
            label="Verify SSL"
            type="checkbox"
            checked={formData.cv_verify as boolean | undefined}
            onChange={(checked) => onChange("cv_verify", checked as boolean)}
            helpText="Verify SSL certificates when connecting to Comic Vine"
          />
          <SettingField
            label="Comic Vine Only"
            type="checkbox"
            checked={formData.cv_only as boolean | undefined}
            onChange={(checked) => onChange("cv_only", checked as boolean)}
            helpText="Use only Comic Vine for metadata (ignore local cache)"
          />
        </SettingGroup>
      )}

      {comicvineEnabled && (
        <SettingGroup
          title="Metron"
          description="Use Metron API for comic search (fixes sorting issues)"
        >
          <SettingField
            label="Use Metron for Search"
            type="checkbox"
            checked={formData.use_metron_search as boolean | undefined}
            onChange={(checked) =>
              onChange("use_metron_search", checked as boolean)
            }
            helpText="Use Metron API instead of Comic Vine for search results"
          />
          <SettingField
            label="Metron Username"
            value={formData.metron_username as string | undefined}
            type="text"
            onChange={(value) => onChange("metron_username", value as string)}
            placeholder="Your Metron username"
            helpText="Register at https://metron.cloud"
          />
          <SettingField
            label="Metron Password"
            value={formData.metron_password as string | undefined}
            type="password"
            onChange={(value) => onChange("metron_password", value as string)}
            placeholder={
              metronPasswordIsSet
                ? "Password saved (enter new value to change)"
                : "Your Metron password"
            }
            helpText={
              metronPasswordIsSet && !formData.metron_password
                ? "Metron password is configured. Enter a new value to change it."
                : "Register at https://metron.cloud"
            }
          />
        </SettingGroup>
      )}

      <SettingGroup
        title="MyAnimeList"
        description="Use MAL as primary manga metadata source for better search coverage"
      >
        <SettingField
          label="Enable MAL"
          type="checkbox"
          checked={formData.mal_enabled as boolean | undefined}
          onChange={(checked) => onChange("mal_enabled", checked as boolean)}
          helpText="Use MyAnimeList for manga search and metadata (MangaDex still provides chapter data)"
        />
        <SettingField
          label="MAL Client ID"
          value={formData.mal_client_id as string | undefined}
          type="password"
          onChange={(value) => onChange("mal_client_id", value as string)}
          placeholder="Your MAL API Client ID"
          helpText="Get your Client ID from https://myanimelist.net/apiconfig"
        />
      </SettingGroup>

      {mangadexEnabled && (
        <SettingGroup
          title="MangaDex"
          description="Configure MangaDex integration for chapter data"
        >
          <SettingField
            label="Languages"
            value={formData.mangadex_languages as string | undefined}
            type="text"
            onChange={(value) =>
              onChange("mangadex_languages", value as string)
            }
            placeholder="en"
            helpText="Comma-separated language codes (e.g., en,ja)"
          />
          <SettingField
            label="Content Rating"
            value={formData.mangadex_content_rating as string | undefined}
            type="text"
            onChange={(value) =>
              onChange("mangadex_content_rating", value as string)
            }
            placeholder="safe,suggestive"
            helpText="Comma-separated ratings: safe, suggestive, erotica, pornographic"
          />
        </SettingGroup>
      )}
    </div>
  );
}
