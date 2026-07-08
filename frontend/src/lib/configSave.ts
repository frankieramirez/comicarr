const REDACTED_SECRET_FIELDS: Record<string, string> = {
  ai_api_key: "ai_api_key_set",
  comicvine_api: "comicvine_api_set",
  mal_client_id: "mal_client_id_set",
  prowl_keys: "prowl_keys_set",
  slack_webhook_url: "slack_webhook_url_set",
  mattermost_webhook_url: "mattermost_webhook_url_set",
  discord_webhook_url: "discord_webhook_url_set",
};

export function prepareConfigSaveData(
  formData: Record<string, unknown>,
  config?: Record<string, unknown>,
): Record<string, unknown> {
  const saveData = { ...formData };

  delete saveData.api_key;

  for (const [field, indicator] of Object.entries(REDACTED_SECRET_FIELDS)) {
    if (!saveData[field] && config?.[indicator]) {
      delete saveData[field];
    }
  }

  return saveData;
}
