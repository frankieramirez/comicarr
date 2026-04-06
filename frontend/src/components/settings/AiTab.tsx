import { useState } from "react";
import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useAiStatus } from "@/hooks/useAiStatus";
import { apiRequest } from "@/lib/api";
import { CheckCircle2, XCircle, Loader2, Zap } from "lucide-react";

interface AiTabProps {
  config: Record<string, unknown>;
  formData: Record<string, unknown>;
  onChange: (key: string, value: string | boolean | number) => void;
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

  const baseUrl = (formData.ai_base_url as string) || "";
  const apiKey = (formData.ai_api_key as string) || "";
  const model = (formData.ai_model as string) || "";
  const apiKeyIsSet = (_config.ai_api_key_set as boolean) || false;
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
        message: err instanceof Error ? err.message : "Connection test failed",
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

  return (
    <div className="space-y-6">
      <SettingGroup
        title="AI Provider"
        description="Configure the OpenAI-compatible API endpoint for AI features"
      >
        <SettingField
          label="Base URL"
          value={formData.ai_base_url as string | undefined}
          type="text"
          onChange={(value) => onChange("ai_base_url", value as string)}
          placeholder="http://localhost:11434/v1"
          helpText="OpenAI-compatible API base URL (e.g., Ollama, LiteLLM, OpenRouter)"
        />
        <SettingField
          label="API Key"
          value={apiKey}
          type="password"
          onChange={(value) => onChange("ai_api_key", value as string)}
          placeholder={
            apiKeyIsSet ? "Key saved (enter new value to change)" : "sk-..."
          }
          helpText={
            apiKeyIsSet && !apiKey
              ? "API key is configured. Enter a new value to change it."
              : "API key for the provider (leave empty if not required)"
          }
        />
        <SettingField
          label="Model Name"
          value={formData.ai_model as string | undefined}
          type="text"
          onChange={(value) => onChange("ai_model", value as string)}
          placeholder="llama3.2:latest"
          helpText="Model identifier to use for AI requests"
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
            <div className="flex items-center gap-2">
              {testResult.success ? (
                <CheckCircle2 className="h-4 w-4 text-green-400" />
              ) : (
                <XCircle className="h-4 w-4 text-destructive" />
              )}
              <span
                className={`text-sm ${testResult.success ? "text-green-400" : "text-destructive"}`}
              >
                {testResult.message}
              </span>
            </div>
          )}
        </div>
      </SettingGroup>

      <SettingGroup
        title="Rate Limits"
        description="Control AI usage to prevent excessive API consumption"
      >
        <SettingField
          label="Timeout (seconds)"
          value={formData.ai_timeout as number | undefined}
          type="number"
          onChange={(value) => onChange("ai_timeout", value as string)}
          placeholder="30"
          helpText="Maximum time to wait for an AI response"
        />
        <SettingField
          label="Requests Per Minute"
          value={formData.ai_rpm_limit as number | undefined}
          type="number"
          onChange={(value) => onChange("ai_rpm_limit", value as string)}
          placeholder="10"
          helpText="Maximum number of AI requests per minute"
        />
        <SettingField
          label="Daily Token Limit"
          value={formData.ai_daily_token_limit as number | undefined}
          type="number"
          onChange={(value) =>
            onChange("ai_daily_token_limit", value as string)
          }
          placeholder="100000"
          helpText="Maximum total tokens per day across all AI features"
        />
      </SettingGroup>

      {status?.configured && (
        <SettingGroup
          title="AI Status"
          description="Current AI service status and usage"
        >
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">Circuit Breaker</p>
              <Badge variant={circuitStateVariant(status.circuit_state)}>
                {status.circuit_state}
              </Badge>
            </div>
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">Today's Requests</p>
              <p className="text-sm font-medium text-foreground">
                {status.today_requests.toLocaleString()}
              </p>
            </div>
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">Today's Tokens</p>
              <p className="text-sm font-medium text-foreground">
                {status.today_tokens.toLocaleString()} /{" "}
                {status.daily_limit.toLocaleString()}
              </p>
            </div>
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">RPM Limit</p>
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
