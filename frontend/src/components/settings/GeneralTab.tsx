import { t } from "@lingui/core/macro";
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
        title={t`Content Sources`}
        description={t`Choose which content sources to enable. At least one must be active.`}
      >
        <SettingField
          label={t`Comics (Comic Vine)`}
          type="checkbox"
          checked={comicvineEnabled}
          onChange={(checked) =>
            onChange("comicvine_enabled", checked as boolean)
          }
          helpText={t`Enable comic search and metadata from Comic Vine`}
        />
        <SettingField
          label={t`Manga (MangaDex)`}
          type="checkbox"
          checked={mangadexEnabled}
          onChange={(checked) =>
            onChange("mangadex_enabled", checked as boolean)
          }
          helpText={t`Enable manga search and metadata from MangaDex`}
        />
      </SettingGroup>

      <SettingGroup
        title={t`Library folder`}
        description={t`Where Comicarr keeps your comics. New series folders are created here and downloads are filed into them.`}
      >
        <SettingField
          label={t`Library folder`}
          value={formData.destination_dir || ""}
          onChange={(v) => onChange("destination_dir", v as string)}
          helpText={t`A folder that already exists on the server. In Docker, use the path inside the container, such as /comics.`}
          placeholder="/comics"
        />
      </SettingGroup>

      <SettingGroup
        title={t`Other folders`}
        description={t`These paths are set in config.ini and are read-only here.`}
      >
        <SettingField
          label={t`Comic Directory`}
          value={config.comic_dir}
          type="text"
          readOnly
          helpText={t`Existing comic folder scanned by library import; imported series stay in place here`}
        />
        <SettingField
          label={t`Manga Directory`}
          value={config.manga_dir}
          type="text"
          readOnly
          helpText={t`Existing manga folder scanned by library import; imported series stay in place here`}
        />
        <SettingField
          label={t`Manga Destination Directory`}
          value={config.manga_destination_dir}
          type="text"
          readOnly
          helpText={t`Root of your organized manga library (falls back to Manga Directory, then Destination Directory)`}
        />
        <SettingField
          label={t`Import Directory`}
          value={config.import_dir}
          type="text"
          readOnly
          helpText={t`Drop folder for new comic/manga files to auto-import`}
        />
        <SettingField
          label={t`Cache Directory`}
          value={config.cache_dir}
          type="text"
          readOnly
          helpText={t`Location for cached data and thumbnails`}
        />
        <SettingField
          label={t`Log Directory`}
          value={config.log_dir}
          type="text"
          readOnly
          helpText={t`Location for application logs`}
        />
      </SettingGroup>
    </div>
  );
}
