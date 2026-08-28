import type {
  ReadableConfig,
  SettingsFormData,
  WritableConfig,
} from "../types/config.generated";

const REDACTED_SECRET_FIELDS: ReadonlyArray<{
  field: keyof WritableConfig;
  indicator: keyof ReadableConfig;
}> = [
  { field: "ai_api_key", indicator: "ai_api_key_set" },
  { field: "comicvine_api", indicator: "comicvine_api_set" },
  { field: "mal_client_id", indicator: "mal_client_id_set" },
  { field: "metron_password", indicator: "metron_password_set" },
  { field: "prowl_keys", indicator: "prowl_keys_set" },
  { field: "slack_webhook_url", indicator: "slack_webhook_url_set" },
  { field: "mattermost_webhook_url", indicator: "mattermost_webhook_url_set" },
  { field: "discord_webhook_url", indicator: "discord_webhook_url_set" },
  { field: "sab_apikey", indicator: "sab_apikey_set" },
];

export function prepareConfigSaveData(
  formData: SettingsFormData & { api_key?: string },
  config?: ReadableConfig,
): SettingsFormData {
  const { api_key: _api_key, ...saveData } = formData;

  for (const { field, indicator } of REDACTED_SECRET_FIELDS) {
    if (!saveData[field] && config?.[indicator]) {
      delete saveData[field];
    }
  }

  const current = config as Record<string, unknown> | undefined;
  const pending = saveData as Record<string, unknown>;
  for (const field of Object.keys(pending)) {
    if (current && field in current && current[field] === pending[field]) {
      delete pending[field];
    }
  }

  return saveData;
}
