import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useState } from "react";
import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useAiStatus } from "@/hooks/useAiStatus";
import { apiRequest } from "@/lib/api";
import { CheckCircle2, XCircle, Loader2, Zap } from "lucide-react";

import type {
  ReadableConfig,
  SettingsFormData,
  WritableConfig,
} from "../../types/config.generated";
import { formatNumber } from "@/lib/intl";

interface AiTabProps {
  config: ReadableConfig;
  formData: SettingsFormData;
  onChange: <K extends keyof WritableConfig>(
    key: K,
    value: NonNullable<WritableConfig[K]>,
  ) => void;
}

interface TestResult {
  success: boolean;
  message: string;
  model?: string;
}

export function AiTab({ config: _config, formData, onChange }: AiTabProps) {
  const { data: status } = useAiStatus();
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  const baseUrl = formData.ai_base_url || "";
  const apiKey = formData.ai_api_key || "";
  const model = formData.ai_model || "";
  const apiKeyIsSet = _config.ai_api_key_set || false;
  const canTest = baseUrl.length > 0 && model.length > 0;

  const handleTestConnection = async () => {
    setIsTesting(true);
    setTestResult(null);
    try {
      const result = await apiRequest<TestResult>("POST", "/api/ai/test", {
        base_url: baseUrl,
        api_key: apiKey,
        model: model,
      });
      setTestResult(result);
    } catch (err) {
      setTestResult({
        success: false,
        message: err instanceof Error ? err.message : t`Connection test failed`,
      });
    } finally {
      setIsTesting(false);
    }
  };

  const circuitStateVariant = (state: string) => {
    if (state === "closed") return "active";
    if (state === "half-open") return "paused";
    return "error";
  };

  const circuitStateLabel = (state: string) => {
    if (state === "closed") return t`closed`;
    if (state === "half-open") return t`half-open`;
    if (state === "open") return t`open`;
    return state;
  };

  return (
    <div className="space-y-6">
      <SettingGroup
        title={t`AI Provider`}
        description={t`Configure the OpenAI-compatible API endpoint for AI features`}
      >
        <SettingField
          label={t`Base URL`}
          value={formData.ai_base_url}
          type="text"
          onChange={(value) => onChange("ai_base_url", value as string)}
          placeholder="http://localhost:11434/v1"
          helpText={t`OpenAI-compatible API base URL (e.g., Ollama, LiteLLM, OpenRouter)`}
        />
        <SettingField
          label={t`API Key`}
          value={apiKey}
          type="password"
          onChange={(value) => onChange("ai_api_key", value as string)}
          placeholder={
            apiKeyIsSet ? t`Key saved (enter new value to change)` : "sk-..."
          }
          helpText={
            apiKeyIsSet && !apiKey
              ? t`API key is configured. Enter a new value to change it.`
              : t`API key for the provider (leave empty if not required)`
          }
        />
        <SettingField
          label={t`Model Name`}
          value={formData.ai_model}
          type="text"
          onChange={(value) => onChange("ai_model", value as string)}
          placeholder="llama3.2:latest"
          helpText={t`Model identifier to use for AI requests`}
        />

        <div className="flex items-center gap-3 pt-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleTestConnection}
            disabled={!canTest || isTesting}
          >
            {isTesting ? (
              <>
                <Loader2 className="h-4 w-4 me-2 animate-spin" />
                <Trans>Testing...</Trans>
              </>
            ) : (
              <>
                <Zap className="h-4 w-4 me-2" />
                <Trans>Test Connection</Trans>
              </>
            )}
          </Button>
          {testResult && (
            <div className="flex items-center gap-2">
              {testResult.success ? (
                <CheckCircle2 className="h-4 w-4 text-[var(--status-active)]" />
              ) : (
                <XCircle className="h-4 w-4 text-destructive" />
              )}
              <span
                className={`text-sm ${testResult.success ? "text-[var(--status-active)]" : "text-destructive"}`}
              >
                {testResult.message}
              </span>
            </div>
          )}
        </div>
      </SettingGroup>

      <SettingGroup
        title={t`Rate Limits`}
        description={t`Control AI usage to prevent excessive API consumption`}
      >
        <SettingField
          label={t`Timeout (seconds)`}
          value={formData.ai_timeout}
          type="number"
          onChange={(value) =>
            onChange("ai_timeout", parseInt(value as string) || 30)
          }
          placeholder="30"
          helpText={t`Maximum time to wait for an AI response`}
        />
        <SettingField
          label={t`Requests Per Minute`}
          value={formData.ai_rpm_limit}
          type="number"
          onChange={(value) =>
            onChange("ai_rpm_limit", parseInt(value as string) || 20)
          }
          placeholder="10"
          helpText={t`Maximum number of AI requests per minute`}
        />
        <SettingField
          label={t`Daily Token Limit`}
          value={formData.ai_daily_token_limit}
          type="number"
          onChange={(value) =>
            onChange(
              "ai_daily_token_limit",
              parseInt(value as string) || 100000,
            )
          }
          placeholder="100000"
          helpText={t`Maximum total tokens per day across all AI features`}
        />
      </SettingGroup>

      {status?.configured && (
        <SettingGroup
          title={t`AI Status`}
          description={t`Current AI service status and usage`}
        >
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">
                <Trans>Circuit Breaker</Trans>
              </p>
              <Badge variant={circuitStateVariant(status.circuit_state)}>
                {circuitStateLabel(status.circuit_state)}
              </Badge>
            </div>
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">
                <Trans>Today's Requests</Trans>
              </p>
              <p className="text-sm font-medium text-foreground">
                {formatNumber(status.today_requests)}
              </p>
            </div>
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">
                <Trans>Today's Tokens</Trans>
              </p>
              <p className="text-sm font-medium text-foreground">
                {formatNumber(status.today_tokens)} /{" "}
                {formatNumber(status.daily_limit)}
              </p>
            </div>
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">
                <Trans>RPM Limit</Trans>
              </p>
              <p className="text-sm font-medium text-foreground">
                {status.rpm_limit}
              </p>
            </div>
          </div>
        </SettingGroup>
      )}
    </div>
  );
}
