import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";
import type {
  ReadableConfig,
  SettingsFormData,
  WritableConfig,
} from "../../types/config.generated";

interface InterfaceTabProps {
  config: ReadableConfig;
  formData: SettingsFormData;
  onChange: <K extends keyof WritableConfig>(
    key: K,
    value: NonNullable<WritableConfig[K]>,
  ) => void;
}

export function InterfaceTab({
  config,
  formData,
  onChange,
}: InterfaceTabProps) {
  return (
    <div className="space-y-6">
      <SettingGroup
        title="Server Settings"
        description="Basic server configuration (read-only, modify in config.ini)"
      >
        <SettingField
          label="Host"
          value={config.http_host}
          type="text"
          readOnly
          helpText="IP address the server listens on"
        />
        <SettingField
          label="Port"
          value={config.http_port}
          type="number"
          readOnly
          helpText="Port number for web interface"
        />
        <SettingField
          label="Username"
          value={config.http_username}
          type="text"
          readOnly
          helpText="HTTP authentication username"
        />
      </SettingGroup>

      <SettingGroup
        title="Interface Preferences"
        description="Customize the look and behavior of the web interface"
      >
        <SettingField
          label="Launch Browser"
          type="checkbox"
          checked={formData.launch_browser}
          onChange={(checked) => onChange("launch_browser", checked as boolean)}
          helpText="Automatically open browser when Comicarr starts"
        />
      </SettingGroup>
    </div>
  );
}
