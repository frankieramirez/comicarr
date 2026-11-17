import { t } from "@lingui/core/macro";
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
        title={t`Server Settings`}
        description={t`Basic server configuration (read-only, modify in config.ini)`}
      >
        <SettingField
          label={t`Host`}
          value={config.http_host}
          type="text"
          readOnly
          helpText={t`IP address the server listens on`}
        />
        <SettingField
          label={t`Port`}
          value={config.http_port}
          type="number"
          readOnly
          helpText={t`Port number for web interface`}
        />
        <SettingField
          label={t`Username`}
          value={config.http_username}
          type="text"
          readOnly
          helpText={t`HTTP authentication username`}
        />
      </SettingGroup>

      <SettingGroup
        title={t`Interface Preferences`}
        description={t`Customize the look and behavior of the web interface`}
      >
        <SettingField
          label={t`Launch Browser`}
          type="checkbox"
          checked={formData.launch_browser}
          onChange={(checked) => onChange("launch_browser", checked as boolean)}
          helpText={t`Automatically open browser when Comicarr starts`}
        />
        <SettingField
          label={t`Cover wall on sign-in`}
          type="checkbox"
          checked={formData.login_cover_wall}
          onChange={(checked) =>
            onChange("login_cover_wall", checked as boolean)
          }
          helpText={t`Show your library's covers behind the sign-in form. Anyone who can reach the sign-in page sees them. Series rated adult are always left out; unrated series can appear.`}
        />
        <SettingField
          label={t`Track print copies`}
          type="checkbox"
          checked={formData.shelf_enabled}
          onChange={(checked) => onChange("shelf_enabled", checked as boolean)}
          helpText={t`Record the physical books you own. Adds a shelf mark to issues and volumes, and a Shelf tab to the Library. It never changes what Comicarr searches for or downloads.`}
        />
      </SettingGroup>
    </div>
  );
}
