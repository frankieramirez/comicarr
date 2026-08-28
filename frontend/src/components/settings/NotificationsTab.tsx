import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";
import type {
  ReadableConfig,
  SettingsFormData,
  WritableConfig,
} from "../../types/config.generated";

interface NotificationsTabProps {
  config: ReadableConfig;
  formData: SettingsFormData;
  onChange: <K extends keyof WritableConfig>(
    key: K,
    value: NonNullable<WritableConfig[K]>,
  ) => void;
}

export function NotificationsTab({
  config,
  formData,
  onChange,
}: NotificationsTabProps) {
  const secretPlaceholder = (
    indicator: keyof ReadableConfig,
    fallback: string,
  ) => (config[indicator] ? "Saved - enter a new value to change" : fallback);

  return (
    <div className="space-y-6">
      {/* Telegram */}
      <SettingGroup
        title="Telegram"
        description="Receive notifications via Telegram bot"
      >
        <SettingField
          label="Enable Telegram"
          type="checkbox"
          checked={formData.telegram_enabled ?? false}
          onChange={(v) => onChange("telegram_enabled", v as boolean)}
        />
        {formData.telegram_enabled && (
          <>
            <SettingField
              label="Bot Token"
              type="password"
              value={formData.telegram_token || ""}
              onChange={(v) => onChange("telegram_token", v as string)}
              helpText="Token from BotFather"
              placeholder="123456:ABC-DEF..."
            />
            <SettingField
              label="User/Chat ID"
              value={formData.telegram_userid || ""}
              onChange={(v) => onChange("telegram_userid", v as string)}
              helpText="Your Telegram user or chat ID. To post into a forum topic, append the topic ID."
              placeholder="-1007356238347 or -1007356238347:15"
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={formData.telegram_onsnatch ?? false}
              onChange={(v) => onChange("telegram_onsnatch", v as boolean)}
            />
            <SettingField
              label="Include cover image"
              type="checkbox"
              checked={formData.telegram_image ?? false}
              onChange={(v) => onChange("telegram_image", v as boolean)}
            />
          </>
        )}
      </SettingGroup>

      {/* Discord */}
      <SettingGroup
        title="Discord"
        description="Send notifications to a Discord channel via webhook"
      >
        <SettingField
          label="Enable Discord"
          type="checkbox"
          checked={formData.discord_enabled ?? false}
          onChange={(v) => onChange("discord_enabled", v as boolean)}
        />
        {formData.discord_enabled && (
          <>
            <SettingField
              label="Webhook URL"
              value={formData.discord_webhook_url || ""}
              onChange={(v) => onChange("discord_webhook_url", v as string)}
              helpText={
                config.discord_webhook_url_set && !formData.discord_webhook_url
                  ? "Discord webhook is configured. Enter a new URL to change it."
                  : "Discord channel webhook URL"
              }
              placeholder={secretPlaceholder(
                "discord_webhook_url_set",
                "https://discord.com/api/webhooks/...",
              )}
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={formData.discord_onsnatch ?? false}
              onChange={(v) => onChange("discord_onsnatch", v as boolean)}
            />
          </>
        )}
      </SettingGroup>

      {/* Slack */}
      <SettingGroup
        title="Slack"
        description="Send notifications to a Slack channel via webhook"
      >
        <SettingField
          label="Enable Slack"
          type="checkbox"
          checked={formData.slack_enabled ?? false}
          onChange={(v) => onChange("slack_enabled", v as boolean)}
        />
        {formData.slack_enabled && (
          <>
            <SettingField
              label="Webhook URL"
              value={formData.slack_webhook_url || ""}
              onChange={(v) => onChange("slack_webhook_url", v as string)}
              helpText={
                config.slack_webhook_url_set && !formData.slack_webhook_url
                  ? "Slack webhook is configured. Enter a new URL to change it."
                  : "Slack incoming webhook URL"
              }
              placeholder={secretPlaceholder(
                "slack_webhook_url_set",
                "https://hooks.slack.com/services/...",
              )}
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={formData.slack_onsnatch ?? false}
              onChange={(v) => onChange("slack_onsnatch", v as boolean)}
            />
          </>
        )}
      </SettingGroup>

      {/* Mattermost */}
      <SettingGroup
        title="Mattermost"
        description="Send notifications to Mattermost via webhook"
      >
        <SettingField
          label="Enable Mattermost"
          type="checkbox"
          checked={formData.mattermost_enabled ?? false}
          onChange={(v) => onChange("mattermost_enabled", v as boolean)}
        />
        {formData.mattermost_enabled && (
          <>
            <SettingField
              label="Webhook URL"
              value={formData.mattermost_webhook_url || ""}
              onChange={(v) => onChange("mattermost_webhook_url", v as string)}
              helpText={
                config.mattermost_webhook_url_set &&
                !formData.mattermost_webhook_url
                  ? "Mattermost webhook is configured. Enter a new URL to change it."
                  : "Mattermost incoming webhook URL"
              }
              placeholder={secretPlaceholder(
                "mattermost_webhook_url_set",
                "https://mattermost.example.com/hooks/...",
              )}
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={formData.mattermost_onsnatch ?? false}
              onChange={(v) => onChange("mattermost_onsnatch", v as boolean)}
            />
          </>
        )}
      </SettingGroup>

      {/* Gotify */}
      <SettingGroup
        title="Gotify"
        description="Self-hosted push notification server"
      >
        <SettingField
          label="Enable Gotify"
          type="checkbox"
          checked={formData.gotify_enabled ?? false}
          onChange={(v) => onChange("gotify_enabled", v as boolean)}
        />
        {formData.gotify_enabled && (
          <>
            <SettingField
              label="Server URL"
              value={formData.gotify_server_url || ""}
              onChange={(v) => onChange("gotify_server_url", v as string)}
              helpText="URL of your Gotify server"
              placeholder="https://gotify.example.com"
            />
            <SettingField
              label="Application Token"
              type="password"
              value={formData.gotify_token || ""}
              onChange={(v) => onChange("gotify_token", v as string)}
              helpText="Gotify application token"
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={formData.gotify_onsnatch ?? false}
              onChange={(v) => onChange("gotify_onsnatch", v as boolean)}
            />
          </>
        )}
      </SettingGroup>

      {/* Matrix */}
      <SettingGroup
        title="Matrix"
        description="Send notifications to a Matrix room"
      >
        <SettingField
          label="Enable Matrix"
          type="checkbox"
          checked={formData.matrix_enabled ?? false}
          onChange={(v) => onChange("matrix_enabled", v as boolean)}
        />
        {formData.matrix_enabled && (
          <>
            <SettingField
              label="Homeserver URL"
              value={formData.matrix_homeserver || ""}
              onChange={(v) => onChange("matrix_homeserver", v as string)}
              placeholder="https://matrix.org"
            />
            <SettingField
              label="Access Token"
              type="password"
              value={formData.matrix_access_token || ""}
              onChange={(v) => onChange("matrix_access_token", v as string)}
            />
            <SettingField
              label="Room ID"
              value={formData.matrix_room_id || ""}
              onChange={(v) => onChange("matrix_room_id", v as string)}
              placeholder="!roomid:matrix.org"
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={formData.matrix_onsnatch ?? false}
              onChange={(v) => onChange("matrix_onsnatch", v as boolean)}
            />
          </>
        )}
      </SettingGroup>

      {/* Pushover */}
      <SettingGroup
        title="Pushover"
        description="Push notifications via Pushover"
      >
        <SettingField
          label="Enable Pushover"
          type="checkbox"
          checked={formData.pushover_enabled ?? false}
          onChange={(v) => onChange("pushover_enabled", v as boolean)}
        />
        {formData.pushover_enabled && (
          <>
            <SettingField
              label="API Key"
              type="password"
              value={formData.pushover_apikey || ""}
              onChange={(v) => onChange("pushover_apikey", v as string)}
              helpText="Your Pushover application API key"
            />
            <SettingField
              label="User Key"
              type="password"
              value={formData.pushover_userkey || ""}
              onChange={(v) => onChange("pushover_userkey", v as string)}
              helpText="Your Pushover user key"
            />
            <SettingField
              label="Device"
              value={formData.pushover_device || ""}
              onChange={(v) => onChange("pushover_device", v as string)}
              helpText="Optional: target specific device"
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={formData.pushover_onsnatch ?? false}
              onChange={(v) => onChange("pushover_onsnatch", v as boolean)}
            />
            <SettingField
              label="Include cover image"
              type="checkbox"
              checked={formData.pushover_image ?? false}
              onChange={(v) => onChange("pushover_image", v as boolean)}
            />
          </>
        )}
      </SettingGroup>

      {/* Prowl */}
      <SettingGroup
        title="Prowl"
        description="iOS push notifications via Prowl"
      >
        <SettingField
          label="Enable Prowl"
          type="checkbox"
          checked={formData.prowl_enabled ?? false}
          onChange={(v) => onChange("prowl_enabled", v as boolean)}
        />
        {formData.prowl_enabled && (
          <>
            <SettingField
              label="API Keys"
              type="password"
              value={formData.prowl_keys || ""}
              onChange={(v) => onChange("prowl_keys", v as string)}
              helpText={
                config.prowl_keys_set && !formData.prowl_keys
                  ? "Prowl API keys are configured. Enter new keys to change them."
                  : "Comma-separated Prowl API keys"
              }
              placeholder={secretPlaceholder(
                "prowl_keys_set",
                "Comma-separated Prowl API keys",
              )}
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={formData.prowl_onsnatch ?? false}
              onChange={(v) => onChange("prowl_onsnatch", v as boolean)}
            />
          </>
        )}
      </SettingGroup>

      {/* Pushbullet */}
      <SettingGroup
        title="Pushbullet"
        description="Push notifications via Pushbullet"
      >
        <SettingField
          label="Enable Pushbullet"
          type="checkbox"
          checked={formData.pushbullet_enabled ?? false}
          onChange={(v) => onChange("pushbullet_enabled", v as boolean)}
        />
        {formData.pushbullet_enabled && (
          <>
            <SettingField
              label="API Key"
              type="password"
              value={formData.pushbullet_apikey || ""}
              onChange={(v) => onChange("pushbullet_apikey", v as string)}
            />
            <SettingField
              label="Device ID"
              value={formData.pushbullet_deviceid || ""}
              onChange={(v) => onChange("pushbullet_deviceid", v as string)}
              helpText="Optional: target specific device"
            />
            <SettingField
              label="Channel Tag"
              value={formData.pushbullet_channel_tag || ""}
              onChange={(v) => onChange("pushbullet_channel_tag", v as string)}
              helpText="Optional: publish to a channel"
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={formData.pushbullet_onsnatch ?? false}
              onChange={(v) => onChange("pushbullet_onsnatch", v as boolean)}
            />
          </>
        )}
      </SettingGroup>

      {/* Boxcar */}
      <SettingGroup title="Boxcar" description="Push notifications via Boxcar">
        <SettingField
          label="Enable Boxcar"
          type="checkbox"
          checked={formData.boxcar_enabled ?? false}
          onChange={(v) => onChange("boxcar_enabled", v as boolean)}
        />
        {formData.boxcar_enabled && (
          <>
            <SettingField
              label="Access Token"
              type="password"
              value={formData.boxcar_token || ""}
              onChange={(v) => onChange("boxcar_token", v as string)}
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={formData.boxcar_onsnatch ?? false}
              onChange={(v) => onChange("boxcar_onsnatch", v as boolean)}
            />
          </>
        )}
      </SettingGroup>

      {/* Email */}
      <SettingGroup title="Email" description="Send notifications via email">
        <SettingField
          label="Enable Email"
          type="checkbox"
          checked={formData.email_enabled ?? false}
          onChange={(v) => onChange("email_enabled", v as boolean)}
        />
        {formData.email_enabled && (
          <>
            <SettingField
              label="From Address"
              value={formData.email_from || ""}
              onChange={(v) => onChange("email_from", v as string)}
              placeholder="comicarr@example.com"
            />
            <SettingField
              label="To Address"
              value={formData.email_to || ""}
              onChange={(v) => onChange("email_to", v as string)}
              placeholder="you@example.com"
            />
            <SettingField
              label="SMTP Server"
              value={formData.email_server || ""}
              onChange={(v) => onChange("email_server", v as string)}
              placeholder="smtp.example.com"
            />
            <SettingField
              label="SMTP Port"
              type="number"
              value={formData.email_port}
              onChange={(v) =>
                onChange("email_port", parseInt(v as string) || 25)
              }
              placeholder="25"
            />
            <SettingField
              label="Username"
              value={formData.email_user || ""}
              onChange={(v) => onChange("email_user", v as string)}
            />
            <SettingField
              label="Password"
              type="password"
              value={formData.email_password || ""}
              onChange={(v) => onChange("email_password", v as string)}
            />
            <SettingField
              label="Encryption"
              type="select"
              value={formData.email_enc}
              onChange={(v) =>
                onChange("email_enc", parseInt(v as string) || 0)
              }
              options={[
                { value: 0, label: "None" },
                { value: 1, label: "TLS/SSL" },
                { value: 2, label: "STARTTLS" },
              ]}
            />
            <SettingField
              label="Notify on grab"
              type="checkbox"
              checked={formData.email_ongrab ?? false}
              onChange={(v) => onChange("email_ongrab", v as boolean)}
            />
            <SettingField
              label="Notify on post-processing"
              type="checkbox"
              checked={formData.email_onpost ?? false}
              onChange={(v) => onChange("email_onpost", v as boolean)}
            />
          </>
        )}
      </SettingGroup>
    </div>
  );
}
