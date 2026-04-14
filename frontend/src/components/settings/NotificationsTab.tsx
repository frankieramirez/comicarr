import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";

interface NotificationsTabProps {
  config: Record<string, unknown>;
  formData: Record<string, unknown>;
  onChange: (key: string, value: string | boolean | number) => void;
}

export function NotificationsTab({
  config: _config,
  formData,
  onChange,
}: NotificationsTabProps) {
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
          checked={(formData.telegram_enabled as boolean) ?? false}
          onChange={(v) => onChange("telegram_enabled", v as boolean)}
        />
        {(formData.telegram_enabled as boolean) && (
          <>
            <SettingField
              label="Bot Token"
              type="password"
              value={(formData.telegram_token as string) || ""}
              onChange={(v) => onChange("telegram_token", v as string)}
              helpText="Token from BotFather"
              placeholder="123456:ABC-DEF..."
            />
            <SettingField
              label="User/Chat ID"
              value={(formData.telegram_userid as string) || ""}
              onChange={(v) => onChange("telegram_userid", v as string)}
              helpText="Your Telegram user or chat ID"
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={(formData.telegram_onsnatch as boolean) ?? false}
              onChange={(v) => onChange("telegram_onsnatch", v as boolean)}
            />
            <SettingField
              label="Include cover image"
              type="checkbox"
              checked={(formData.telegram_image as boolean) ?? false}
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
          checked={(formData.discord_enabled as boolean) ?? false}
          onChange={(v) => onChange("discord_enabled", v as boolean)}
        />
        {(formData.discord_enabled as boolean) && (
          <>
            <SettingField
              label="Webhook URL"
              value={(formData.discord_webhook_url as string) || ""}
              onChange={(v) => onChange("discord_webhook_url", v as string)}
              helpText="Discord channel webhook URL"
              placeholder="https://discord.com/api/webhooks/..."
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={(formData.discord_onsnatch as boolean) ?? false}
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
          checked={(formData.slack_enabled as boolean) ?? false}
          onChange={(v) => onChange("slack_enabled", v as boolean)}
        />
        {(formData.slack_enabled as boolean) && (
          <>
            <SettingField
              label="Webhook URL"
              value={(formData.slack_webhook_url as string) || ""}
              onChange={(v) => onChange("slack_webhook_url", v as string)}
              helpText="Slack incoming webhook URL"
              placeholder="https://hooks.slack.com/services/..."
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={(formData.slack_onsnatch as boolean) ?? false}
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
          checked={(formData.mattermost_enabled as boolean) ?? false}
          onChange={(v) => onChange("mattermost_enabled", v as boolean)}
        />
        {(formData.mattermost_enabled as boolean) && (
          <>
            <SettingField
              label="Webhook URL"
              value={(formData.mattermost_webhook_url as string) || ""}
              onChange={(v) => onChange("mattermost_webhook_url", v as string)}
              helpText="Mattermost incoming webhook URL"
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={(formData.mattermost_onsnatch as boolean) ?? false}
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
          checked={(formData.gotify_enabled as boolean) ?? false}
          onChange={(v) => onChange("gotify_enabled", v as boolean)}
        />
        {(formData.gotify_enabled as boolean) && (
          <>
            <SettingField
              label="Server URL"
              value={(formData.gotify_server_url as string) || ""}
              onChange={(v) => onChange("gotify_server_url", v as string)}
              helpText="URL of your Gotify server"
              placeholder="https://gotify.example.com"
            />
            <SettingField
              label="Application Token"
              type="password"
              value={(formData.gotify_token as string) || ""}
              onChange={(v) => onChange("gotify_token", v as string)}
              helpText="Gotify application token"
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={(formData.gotify_onsnatch as boolean) ?? false}
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
          checked={(formData.matrix_enabled as boolean) ?? false}
          onChange={(v) => onChange("matrix_enabled", v as boolean)}
        />
        {(formData.matrix_enabled as boolean) && (
          <>
            <SettingField
              label="Homeserver URL"
              value={(formData.matrix_homeserver as string) || ""}
              onChange={(v) => onChange("matrix_homeserver", v as string)}
              placeholder="https://matrix.org"
            />
            <SettingField
              label="Access Token"
              type="password"
              value={(formData.matrix_access_token as string) || ""}
              onChange={(v) => onChange("matrix_access_token", v as string)}
            />
            <SettingField
              label="Room ID"
              value={(formData.matrix_room_id as string) || ""}
              onChange={(v) => onChange("matrix_room_id", v as string)}
              placeholder="!roomid:matrix.org"
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={(formData.matrix_onsnatch as boolean) ?? false}
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
          checked={(formData.pushover_enabled as boolean) ?? false}
          onChange={(v) => onChange("pushover_enabled", v as boolean)}
        />
        {(formData.pushover_enabled as boolean) && (
          <>
            <SettingField
              label="API Key"
              type="password"
              value={(formData.pushover_apikey as string) || ""}
              onChange={(v) => onChange("pushover_apikey", v as string)}
              helpText="Your Pushover application API key"
            />
            <SettingField
              label="User Key"
              type="password"
              value={(formData.pushover_userkey as string) || ""}
              onChange={(v) => onChange("pushover_userkey", v as string)}
              helpText="Your Pushover user key"
            />
            <SettingField
              label="Device"
              value={(formData.pushover_device as string) || ""}
              onChange={(v) => onChange("pushover_device", v as string)}
              helpText="Optional: target specific device"
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={(formData.pushover_onsnatch as boolean) ?? false}
              onChange={(v) => onChange("pushover_onsnatch", v as boolean)}
            />
            <SettingField
              label="Include cover image"
              type="checkbox"
              checked={(formData.pushover_image as boolean) ?? false}
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
          checked={(formData.prowl_enabled as boolean) ?? false}
          onChange={(v) => onChange("prowl_enabled", v as boolean)}
        />
        {(formData.prowl_enabled as boolean) && (
          <>
            <SettingField
              label="API Keys"
              type="password"
              value={(formData.prowl_keys as string) || ""}
              onChange={(v) => onChange("prowl_keys", v as string)}
              helpText="Comma-separated Prowl API keys"
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={(formData.prowl_onsnatch as boolean) ?? false}
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
          checked={(formData.pushbullet_enabled as boolean) ?? false}
          onChange={(v) => onChange("pushbullet_enabled", v as boolean)}
        />
        {(formData.pushbullet_enabled as boolean) && (
          <>
            <SettingField
              label="API Key"
              type="password"
              value={(formData.pushbullet_apikey as string) || ""}
              onChange={(v) => onChange("pushbullet_apikey", v as string)}
            />
            <SettingField
              label="Device ID"
              value={(formData.pushbullet_deviceid as string) || ""}
              onChange={(v) => onChange("pushbullet_deviceid", v as string)}
              helpText="Optional: target specific device"
            />
            <SettingField
              label="Channel Tag"
              value={(formData.pushbullet_channel_tag as string) || ""}
              onChange={(v) => onChange("pushbullet_channel_tag", v as string)}
              helpText="Optional: publish to a channel"
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={(formData.pushbullet_onsnatch as boolean) ?? false}
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
          checked={(formData.boxcar_enabled as boolean) ?? false}
          onChange={(v) => onChange("boxcar_enabled", v as boolean)}
        />
        {(formData.boxcar_enabled as boolean) && (
          <>
            <SettingField
              label="Access Token"
              type="password"
              value={(formData.boxcar_token as string) || ""}
              onChange={(v) => onChange("boxcar_token", v as string)}
            />
            <SettingField
              label="Notify on snatch"
              type="checkbox"
              checked={(formData.boxcar_onsnatch as boolean) ?? false}
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
          checked={(formData.email_enabled as boolean) ?? false}
          onChange={(v) => onChange("email_enabled", v as boolean)}
        />
        {(formData.email_enabled as boolean) && (
          <>
            <SettingField
              label="From Address"
              value={(formData.email_from as string) || ""}
              onChange={(v) => onChange("email_from", v as string)}
              placeholder="comicarr@example.com"
            />
            <SettingField
              label="To Address"
              value={(formData.email_to as string) || ""}
              onChange={(v) => onChange("email_to", v as string)}
              placeholder="you@example.com"
            />
            <SettingField
              label="SMTP Server"
              value={(formData.email_server as string) || ""}
              onChange={(v) => onChange("email_server", v as string)}
              placeholder="smtp.example.com"
            />
            <SettingField
              label="SMTP Port"
              type="number"
              value={formData.email_port as number | undefined}
              onChange={(v) =>
                onChange("email_port", parseInt(v as string) || 25)
              }
              placeholder="25"
            />
            <SettingField
              label="Username"
              value={(formData.email_user as string) || ""}
              onChange={(v) => onChange("email_user", v as string)}
            />
            <SettingField
              label="Password"
              type="password"
              value={(formData.email_password as string) || ""}
              onChange={(v) => onChange("email_password", v as string)}
            />
            <SettingField
              label="Encryption"
              type="select"
              value={formData.email_enc as number | undefined}
              onChange={(v) => onChange("email_enc", parseInt(v as string))}
              options={[
                { value: 0, label: "None" },
                { value: 1, label: "TLS/SSL" },
                { value: 2, label: "STARTTLS" },
              ]}
            />
            <SettingField
              label="Notify on grab"
              type="checkbox"
              checked={(formData.email_ongrab as boolean) ?? true}
              onChange={(v) => onChange("email_ongrab", v as boolean)}
            />
            <SettingField
              label="Notify on post-processing"
              type="checkbox"
              checked={(formData.email_onpost as boolean) ?? true}
              onChange={(v) => onChange("email_onpost", v as boolean)}
            />
          </>
        )}
      </SettingGroup>
    </div>
  );
}
