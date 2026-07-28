import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";
import type {
  ReadableConfig,
  SettingsFormData,
  WritableConfig,
} from "../../types/config.generated";

interface GeneralTabProps {
  config: ReadableConfig;
  formData: SettingsFormData;
  onChange: <K extends keyof WritableConfig>(
    key: K,
    value: NonNullable<WritableConfig[K]>,
  ) => void;
}

export function GeneralTab({ config, formData, onChange }: GeneralTabProps) {
  const comicvineEnabled = formData.comicvine_enabled ?? true;
  const mangadexEnabled = formData.mangadex_enabled ?? false;

  return (
    <div className="space-y-6">
      <SettingGroup
        title="Content Sources"
        description="Choose which content sources to enable. At least one must be active."
      >
        <SettingField
          label="Comics (Comic Vine)"
          type="checkbox"
          checked={comicvineEnabled}
          onChange={(checked) =>
            onChange("comicvine_enabled", checked as boolean)
          }
          helpText="Enable comic search and metadata from Comic Vine"
        />
        <SettingField
          label="Manga (MangaDex)"
          type="checkbox"
          checked={mangadexEnabled}
          onChange={(checked) =>
            onChange("mangadex_enabled", checked as boolean)
          }
          helpText="Enable manga search and metadata from MangaDex"
        />
      </SettingGroup>

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
          label="Manga Directory"
          value={config.manga_dir}
          type="text"
          readOnly
          helpText="Location where your manga library is stored"
        />
        <SettingField
          label="Manga Destination Directory"
          value={config.manga_destination_dir}
          type="text"
          readOnly
          helpText="Default destination for downloaded manga (falls back to Manga Directory, then Destination Directory)"
        />
        <SettingField
          label="Import Directory"
          value={config.import_dir}
          type="text"
          readOnly
          helpText="Drop folder for new comic/manga files to auto-import"
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
