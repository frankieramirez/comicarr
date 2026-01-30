import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";

interface GeneralTabProps {
  config: Record<string, unknown>;
}

export function GeneralTab({ config }: GeneralTabProps) {
  return (
    <div className="space-y-6">
      <SettingGroup
        title="Directories"
        description="These paths are configured in your config.ini file and are read-only."
      >
        <SettingField
          label="Comic Directory"
          value={config.comic_dir as string | undefined}
          type="text"
          readOnly
          helpText="Location where your comic library is stored"
        />
        <SettingField
          label="Destination Directory"
          value={config.destination_dir as string | undefined}
          type="text"
          readOnly
          helpText="Default destination for downloaded comics"
        />
        <SettingField
          label="Cache Directory"
          value={config.cache_dir as string | undefined}
          type="text"
          readOnly
          helpText="Location for cached data and thumbnails"
        />
        <SettingField
          label="Log Directory"
          value={config.log_dir as string | undefined}
          type="text"
          readOnly
          helpText="Location for application logs"
        />
      </SettingGroup>
    </div>
  );
}
