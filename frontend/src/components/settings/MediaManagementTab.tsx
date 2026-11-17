import { t } from "@lingui/core/macro";
import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";
import type {
  ReadableConfig,
  SettingsFormData,
  WritableConfig,
} from "../../types/config.generated";
import { CONFIG_MINIMUMS } from "../../types/config.generated";
import { minimumHint, typedInteger } from "@/lib/settingValues";

const IMPORT_FILE_OPTS_INHERIT = "file_opts";
const IMPORT_FILE_OPTS_OPTIONS = () => [
  { value: IMPORT_FILE_OPTS_INHERIT, label: t`Same as downloads` },
  { value: "move", label: t`Move` },
  { value: "copy", label: t`Copy` },
  { value: "hardlink", label: t`Hardlink` },
  { value: "softlink", label: t`Softlink` },
];

function importFileOptsSelectValue(value?: string): string {
  const normalized = value?.trim().toLowerCase();
  if (!normalized || normalized === "none") {
    return IMPORT_FILE_OPTS_INHERIT;
  }
  return normalized;
}

interface MediaManagementTabProps {
  config: ReadableConfig;
  formData: SettingsFormData;
  onChange: <K extends keyof WritableConfig>(
    key: K,
    value: NonNullable<WritableConfig[K]>,
  ) => void;
  /** Refusals keyed by field, shown under the field. */
  errors?: Record<string, string>;
}

export function MediaManagementTab({
  config: _config,
  formData,
  onChange,
  errors,
}: MediaManagementTabProps) {
  return (
    <div className="space-y-6">
      <SettingGroup
        title={t`Library folders`}
        description={t`Where your comics and manga live. Downloads are filed here, and Import scans these folders for what you already have.`}
      >
        <SettingField
          label={t`Library folder`}
          value={formData.destination_dir || ""}
          onChange={(v) => onChange("destination_dir", v as string)}
          helpText={t`New comic series folders are created here. A folder that already exists on the server. In Docker, use the path inside the container, such as /comics.`}
          placeholder="/comics"
        />
        <SettingField
          label={t`Manga library folder`}
          value={formData.manga_destination_dir || ""}
          onChange={(v) => onChange("manga_destination_dir", v as string)}
          helpText={t`New manga series folders are created here. Leave blank to use the library folder.`}
          placeholder="/manga"
        />
      </SettingGroup>

      <SettingGroup
        title={t`Import folders`}
        description={t`Optional. Leave these blank and Import scans the library folders above.`}
      >
        <SettingField
          label={t`Comic folder to scan`}
          value={formData.comic_dir || ""}
          onChange={(v) => onChange("comic_dir", v as string)}
          helpText={t`An existing comic collection somewhere else. Imported series stay where they are. Blank scans the library folder.`}
          placeholder={formData.destination_dir || "/comics"}
        />
        <SettingField
          label={t`Manga folder to scan`}
          value={formData.manga_dir || ""}
          onChange={(v) => onChange("manga_dir", v as string)}
          helpText={t`An existing manga collection somewhere else. Blank scans the manga library folder. Manga scans never use the comic library folder.`}
          placeholder={formData.manga_destination_dir || "/manga"}
        />
        <SettingField
          label={t`Import folder`}
          value={formData.import_dir || ""}
          onChange={(v) => onChange("import_dir", v as string)}
          helpText={t`A drop folder. Files you put here are matched and filed into your library. It cannot be inside, or contain, a library or download folder.`}
          placeholder="/imports"
        />
      </SettingGroup>

      {/* File Naming */}
      <SettingGroup
        title={t`File Naming`}
        description={t`Control how files and folders are named in your library`}
      >
        <SettingField
          label={t`Folder Format`}
          value={formData.folder_format || ""}
          onChange={(v) => onChange("folder_format", v as string)}
          helpText={t`Pattern for series folders. Variables: $Series, $Year, $Publisher`}
          placeholder={t`$Series ($Year)`}
        />
        <SettingField
          label={t`File Format`}
          value={formData.file_format || ""}
          onChange={(v) => onChange("file_format", v as string)}
          helpText={t`Pattern for issue files. Variables: $Series, $Issue, $Year, $Title`}
          placeholder={t`$Series $Issue ($Year)`}
        />
        <SettingField
          label={t`Lowercase filenames`}
          type="checkbox"
          checked={formData.lowercase_filenames ?? false}
          onChange={(v) => onChange("lowercase_filenames", v as boolean)}
          helpText={t`Convert all filenames to lowercase`}
        />
        <SettingField
          label={t`Replace spaces with underscores`}
          type="checkbox"
          checked={formData.replace_spaces ?? false}
          onChange={(v) => onChange("replace_spaces", v as boolean)}
        />
      </SettingGroup>

      <SettingGroup
        title={t`Series Folders`}
        description={t`A series can use its own folder inside any library root. The destination and manga destination directories are always roots.`}
      >
        <SettingField
          label={t`Additional library roots`}
          type="textarea"
          value={formData.additional_library_roots || ""}
          onChange={(v) => onChange("additional_library_roots", v as string)}
          helpText={t`One server path per line, such as /comics/Magazines. In Docker, use the path inside the container.`}
          placeholder="/comics/Magazines"
        />
        <SettingField
          label={t`Magazine destination`}
          value={formData.magazine_destination_dir || ""}
          onChange={(v) => onChange("magazine_destination_dir", v as string)}
          helpText={t`Library root for Series cataloged as Magazine. When set, cataloging a Series as Magazine stores it here unless you chose its folder. In Docker, use the path inside the container.`}
          placeholder="/magazines"
        />
      </SettingGroup>

      {/* Import Behavior */}
      <SettingGroup
        title={t`Import Behavior`}
        description={t`How files are handled during import and post-processing`}
      >
        <SettingField
          label={t`Place imported files in the library`}
          type="checkbox"
          checked={formData.imp_move ?? false}
          onChange={(v) => onChange("imp_move", v as boolean)}
          helpText={t`Put Import Inbox files into the series folder. When off, they stay in the import directory and are marked Archived. Import file operation decides whether they are moved, copied, or linked.`}
        />
        <SettingField
          label={t`Import file operation`}
          type="select"
          value={importFileOptsSelectValue(formData.imp_file_opts)}
          options={IMPORT_FILE_OPTS_OPTIONS()}
          onChange={(v) =>
            onChange(
              "imp_file_opts",
              v === IMPORT_FILE_OPTS_INHERIT ? "" : (v as string),
            )
          }
          helpText={t`How Import Inbox files get into the library when Place imported files in the library is on. Same as downloads follows the post-processing file operation, so torrent users can keep downloads on copy and set imports to move. Softlink leaves the file in the import directory and links to it, so don't clear the import directory.`}
        />
        <SettingField
          label={t`Rename files on import`}
          type="checkbox"
          checked={formData.imp_rename ?? false}
          onChange={(v) => onChange("imp_rename", v as boolean)}
          helpText={t`Rename imported files using the file format pattern`}
        />
        <SettingField
          label={t`Write metadata on import`}
          type="checkbox"
          checked={formData.imp_metadata ?? false}
          onChange={(v) => onChange("imp_metadata", v as boolean)}
          helpText={t`Tag imported files with ComicInfo.xml metadata`}
        />
        <SettingField
          label={t`Create series folders`}
          type="checkbox"
          checked={formData.imp_seriesfolders ?? false}
          onChange={(v) => onChange("imp_seriesfolders", v as boolean)}
          helpText={t`Automatically create series folders for imported files`}
        />
        <SettingField
          label={t`Auto-import`}
          type="checkbox"
          checked={formData.auto_import_enabled ?? true}
          onChange={(v) => onChange("auto_import_enabled", v as boolean)}
          helpText={t`Automatically import matching files from the Import Inbox. Turn off to review every file; suggested matches are kept.`}
        />
        <SettingField
          label={t`Auto-import confidence`}
          type="number"
          min={0}
          value={formData.auto_import_confidence}
          disabled={!(formData.auto_import_enabled ?? true)}
          onChange={(v) => {
            const n = parseInt(v as string);
            onChange("auto_import_confidence", Number.isNaN(n) ? 80 : n);
          }}
          helpText={t`Only applies when auto-import is on. Minimum series match score (0–100) for the Import Inbox to import files without review. Files whose issue number is missing from the matched series always go to review. Set above 100 to review everything (default: 80).`}
        />
      </SettingGroup>

      {/* Scheduling */}
      <SettingGroup
        title={t`Scheduling`}
        description={t`Intervals for automated background tasks (in minutes)`}
      >
        <SettingField
          label={t`Search Interval`}
          type="number"
          min={CONFIG_MINIMUMS.search_interval}
          value={formData.search_interval}
          onChange={(v) => onChange("search_interval", typedInteger(v))}
          helpText={`${t`How often to search for wanted issues (default: 360 min)`} ${minimumHint("search_interval")}`}
          error={errors?.search_interval}
        />
        <SettingField
          label={t`RSS Check Interval`}
          type="number"
          min={CONFIG_MINIMUMS.rss_checkinterval}
          value={formData.rss_checkinterval}
          onChange={(v) => onChange("rss_checkinterval", typedInteger(v))}
          helpText={`${t`How often to check RSS feeds (default: 20 min)`} ${minimumHint("rss_checkinterval")}`}
          error={errors?.rss_checkinterval}
        />
        <SettingField
          label={t`Database Update Interval`}
          type="number"
          min={CONFIG_MINIMUMS.dbupdate_interval}
          value={formData.dbupdate_interval}
          onChange={(v) => onChange("dbupdate_interval", typedInteger(v))}
          helpText={`${t`How often to update series metadata from providers, in minutes (default: 1440 = 24 hours)`} ${minimumHint("dbupdate_interval")}`}
          error={errors?.dbupdate_interval}
        />
      </SettingGroup>

      {/* Quality & Organization */}
      <SettingGroup
        title={t`Quality & Organization`}
        description={t`Additional library management preferences`}
      >
        <SettingField
          label={t`Include annuals`}
          type="checkbox"
          checked={formData.annuals_on ?? false}
          onChange={(v) => onChange("annuals_on", v as boolean)}
          helpText={t`Automatically include annual issues when monitoring series`}
        />
        <SettingField
          label={t`Create weekly folders`}
          type="checkbox"
          checked={formData.weekfolder ?? false}
          onChange={(v) => onChange("weekfolder", v as boolean)}
          helpText={t`Organize downloads into weekly subfolders`}
        />
        <SettingField
          label={t`Enable metadata tagging`}
          type="checkbox"
          checked={formData.enable_meta ?? false}
          onChange={(v) => onChange("enable_meta", v as boolean)}
          helpText={t`Write ComicInfo.xml metadata to downloaded files`}
        />
      </SettingGroup>
    </div>
  );
}
