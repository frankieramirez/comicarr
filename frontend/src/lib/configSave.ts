import type {
  ReadableConfig,
  SettingsFormData,
  WritableConfig,
} from "../types/config.generated";

// Write-only secrets the backend redacts: `GET /api/config` omits the value
// and sends a boolean indicator instead. An empty field with the indicator
// set means "unchanged", so the key is dropped rather than clearing the
// stored secret.
const REDACTED_SECRET_FIELDS: ReadonlyArray<{
  field: keyof WritableConfig;
  indicator: keyof ReadableConfig;
}> = [
  { field: "ai_api_key", indicator: "ai_api_key_set" },
  { field: "comicvine_api", indicator: "comicvine_api_set" },
  { field: "mal_client_id", indicator: "mal_client_id_set" },
  { field: "prowl_keys", indicator: "prowl_keys_set" },
  { field: "slack_webhook_url", indicator: "slack_webhook_url_set" },
  { field: "mattermost_webhook_url", indicator: "mattermost_webhook_url_set" },
  { field: "discord_webhook_url", indicator: "discord_webhook_url_set" },
];

export function prepareConfigSaveData(
  formData: SettingsFormData & { api_key?: string },
  config?: ReadableConfig,
): SettingsFormData {
  // The raw API key must never ride along on a settings save, however it
  // might end up in form state. api_key has no readable or writable registry
  // entry, so it is typed here as an explicit extra.
  const { api_key: _api_key, ...saveData } = formData;

  for (const { field, indicator } of REDACTED_SECRET_FIELDS) {
    if (!saveData[field] && config?.[indicator]) {
      delete saveData[field];
    }
  }

  return saveData;
}
