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
        title={t`Server folders`}
        description={t`Set in config.ini and read-only here. Library and import folders are under Folders and naming.`}
      >
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
