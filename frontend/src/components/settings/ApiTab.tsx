import { useState } from "react";
import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { Copy, RefreshCw } from "lucide-react";

interface ApiTabProps {
  config: Record<string, unknown>;
  formData: Record<string, unknown>;
  onChange: (key: string, value: string | boolean) => void;
}

export function ApiTab({ config, formData, onChange }: ApiTabProps) {
  const { addToast } = useToast();
  const [isRegenerating, setIsRegenerating] = useState(false);

  const handleCopyApiKey = async () => {
    try {
      await navigator.clipboard.writeText((config.api_key as string) ?? "");
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

    setIsRegenerating(true);
    try {
      const newApiKey = crypto.randomUUID();
      onChange("api_key", newApiKey);
      addToast({
        type: "success",
        message: "API key regenerated. Remember to save your changes!",
      });
    } catch {
      addToast({
        type: "error",
        message: "Failed to regenerate API key",
      });
    } finally {
      setIsRegenerating(false);
    }
  };

  return (
    <div className="space-y-6">
      <SettingGroup
        title="Mylar API Key"
        description="This key is used to authenticate API requests to Mylar"
      >
        <div className="space-y-2">
          <label className="text-sm font-medium">API Key</label>
          <div className="flex space-x-2">
            <input
              type="text"
              value={
                (formData.api_key as string) || (config.api_key as string) || ""
              }
              readOnly
              className="flex-1 px-3 py-2 border border-input rounded-md bg-background font-mono text-sm"
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={handleCopyApiKey}
              title="Copy to clipboard"
            >
              <Copy className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={handleRegenerateApiKey}
              disabled={isRegenerating}
              title="Regenerate API key"
            >
              <RefreshCw
                className={`h-4 w-4 ${isRegenerating ? "animate-spin" : ""}`}
              />
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Use this key in API requests and integrations
          </p>
        </div>
      </SettingGroup>

      <SettingGroup
        title="Comic Vine API"
        description="Configure Comic Vine integration for metadata"
      >
        <SettingField
          label="Comic Vine API Key"
          value={formData.comicvine_api as string | undefined}
          type="text"
          onChange={(value) => onChange("comicvine_api", value as string)}
          placeholder="Enter your 40-character Comic Vine API key"
          helpText="Get your API key from https://comicvine.gamespot.com/api/"
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

      <SettingGroup
        title="Metron"
        description="Use Metron API for comic search (fixes sorting issues)"
      >
        <SettingField
          label="Use Metron for Search"
          type="checkbox"
          checked={formData.use_metron_search as boolean | undefined}
          onChange={(checked) => onChange("use_metron_search", checked as boolean)}
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
          placeholder="Your Metron password"
        />
      </SettingGroup>
    </div>
  );
}
