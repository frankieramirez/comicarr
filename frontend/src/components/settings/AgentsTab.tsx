import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Copy } from "lucide-react";
import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { MCP_DOCS_URL, mcpEndpointUrl } from "@/lib/mcp";

import type {
  ReadableConfig,
  SettingsFormData,
  WritableConfig,
} from "../../types/config.generated";

// Header examples are code, not text: they stay the same in every language.
const BEARER_HEADER = "Authorization: Bearer <key>";
const API_KEY_HEADER = "X-Api-Key: <key>";

interface AgentsTabProps {
  config: ReadableConfig;
  formData: SettingsFormData;
  onChange: <K extends keyof WritableConfig>(
    key: K,
    value: NonNullable<WritableConfig[K]>,
  ) => void;
}

/** Settings group for the MCP server: the two live toggles and the endpoint. */
export function AgentsTab({ config, formData, onChange }: AgentsTabProps) {
  const { addToast } = useToast();
  const mcpEnabled = formData.mcp_enabled ?? false;
  const endpoint = mcpEndpointUrl(
    window.location.origin,
    formData.http_root ?? config.http_root,
  );

  const handleCopyEndpoint = async () => {
    try {
      await navigator.clipboard.writeText(endpoint);
      addToast({ type: "success", message: t`MCP endpoint copied` });
    } catch {
      addToast({ type: "error", message: t`Failed to copy the MCP endpoint` });
    }
  };

  return (
    <div className="space-y-6">
      <SettingGroup
        title={t`Agents (MCP)`}
        description={t`Let AI agents such as Claude Code or VS Code read your library, and optionally act on it, through the Model Context Protocol. Changes apply as soon as you save; no restart.`}
      >
        <SettingField
          label={t`Enable MCP server`}
          type="checkbox"
          checked={mcpEnabled}
          onChange={(checked) => onChange("mcp_enabled", checked as boolean)}
          helpText={t`Serve the MCP endpoint below. While this is off, the endpoint does not exist.`}
        />
        <SettingField
          label={t`Allow write tools`}
          type="checkbox"
          checked={formData.mcp_write_enabled ?? false}
          disabled={!mcpEnabled}
          onChange={(checked) =>
            onChange("mcp_write_enabled", checked as boolean)
          }
          helpText={
            mcpEnabled
              ? t`Let agents change things, such as marking issues Wanted, starting searches and adding series. Each write goes through your agent's own approval prompt.`
              : t`Turn on the MCP server first.`
          }
        />
      </SettingGroup>

      <SettingGroup
        title={t`Endpoint`}
        description={t`Point your agent at this URL.`}
      >
        <div className="space-y-2">
          <label
            htmlFor="settings-mcp-endpoint"
            className="text-sm font-medium"
          >
            <Trans>MCP endpoint</Trans>
          </label>
          <div className="flex space-x-2">
            <input
              id="settings-mcp-endpoint"
              type="text"
              value={endpoint}
              readOnly
              className="flex-1 px-3 py-2 border border-input rounded-md bg-background font-mono text-sm"
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={handleCopyEndpoint}
              title={t`Copy MCP endpoint`}
              aria-label={t`Copy MCP endpoint`}
            >
              <Copy className="h-4 w-4" />
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            <Trans>
              Authenticate with your Comicarr API key (Sources and keys), sent
              as <code className="font-mono">{BEARER_HEADER}</code> or{" "}
              <code className="font-mono">{API_KEY_HEADER}</code>.
            </Trans>
          </p>
          {MCP_DOCS_URL && (
            <p className="text-xs">
              <a
                href={MCP_DOCS_URL}
                target="_blank"
                rel="noreferrer"
                className="text-primary underline-offset-2 hover:underline"
              >
                <Trans>Connect an agent (MCP)</Trans>
              </a>
            </p>
          )}
        </div>
      </SettingGroup>
    </div>
  );
}
