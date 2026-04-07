import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";

interface GeneralTabProps {
  config: Record<string, unknown>;
  formData: Record<string, unknown>;
  onChange: (key: string, value: string | boolean) => void;
}

export function GeneralTab({ config, formData, onChange }: GeneralTabProps) {
  const comicvineEnabled = (formData.comicvine_enabled as boolean) ?? true;
  const mangadexEnabled = (formData.mangadex_enabled as boolean) ?? false;

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
          label="Manga Directory"
          value={config.manga_dir as string | undefined}
          type="text"
          readOnly
          helpText="Location where your manga library is stored"
        />
        <SettingField
          label="Manga Destination Directory"
          value={config.manga_destination_dir as string | undefined}
          type="text"
          readOnly
          helpText="Default destination for downloaded manga (falls back to Manga Directory, then Destination Directory)"
        />
        <SettingField
          label="Import Directory"
          value={config.import_dir as string | undefined}
          type="text"
          readOnly
          helpText="Drop folder for new comic/manga files to auto-import"
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
