import { SettingGroup } from './SettingGroup';
import { SettingField } from './SettingField';

export function GeneralTab({ config }) {
  return (
    <div className="space-y-6">
      <SettingGroup
        title="Directories"
        description="These paths are configured in your config.ini file and are read-only."
      >
        <SettingField
          label="Comic Directory"
          value={config.comic_dir}
          type="text"
          readOnly
          helpText="Location where your comic library is stored"
        />
        <SettingField
          label="Destination Directory"
          value={config.destination_dir}
          type="text"
          readOnly
          helpText="Default destination for downloaded comics"
        />
        <SettingField
          label="Cache Directory"
          value={config.cache_dir}
          type="text"
          readOnly
          helpText="Location for cached data and thumbnails"
        />
        <SettingField
          label="Log Directory"
          value={config.log_dir}
          type="text"
          readOnly
          helpText="Location for application logs"
        />
      </SettingGroup>
    </div>
  );
}
