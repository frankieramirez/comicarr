import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";

interface MediaManagementTabProps {
  config: Record<string, unknown>;
  formData: Record<string, unknown>;
  onChange: (key: string, value: string | boolean | number) => void;
}

export function MediaManagementTab({
  config: _config,
  formData,
  onChange,
}: MediaManagementTabProps) {
  return (
    <div className="space-y-6">
      {/* File Naming */}
      <SettingGroup
        title="File Naming"
        description="Control how files and folders are named in your library"
      >
        <SettingField
          label="Folder Format"
          value={(formData.folder_format as string) || ""}
          onChange={(v) => onChange("folder_format", v as string)}
          helpText="Pattern for series folders. Variables: $Series, $Year, $Publisher"
          placeholder="$Series ($Year)"
        />
        <SettingField
          label="File Format"
          value={(formData.file_format as string) || ""}
          onChange={(v) => onChange("file_format", v as string)}
          helpText="Pattern for issue files. Variables: $Series, $Issue, $Year, $Title"
          placeholder="$Series $Issue ($Year)"
        />
        <SettingField
          label="Lowercase filenames"
          type="checkbox"
          checked={(formData.lowercase_filenames as boolean) ?? false}
          onChange={(v) => onChange("lowercase_filenames", v as boolean)}
          helpText="Convert all filenames to lowercase"
        />
        <SettingField
          label="Replace spaces with underscores"
          type="checkbox"
          checked={(formData.replace_spaces as boolean) ?? false}
          onChange={(v) => onChange("replace_spaces", v as boolean)}
        />
      </SettingGroup>

      {/* Import Behavior */}
      <SettingGroup
        title="Import Behavior"
        description="How files are handled during import and post-processing"
      >
        <SettingField
          label="Move files on import"
          type="checkbox"
          checked={(formData.imp_move as boolean) ?? false}
          onChange={(v) => onChange("imp_move", v as boolean)}
          helpText="Move imported files to the library directory"
        />
        <SettingField
          label="Rename files on import"
          type="checkbox"
          checked={(formData.imp_rename as boolean) ?? false}
          onChange={(v) => onChange("imp_rename", v as boolean)}
          helpText="Rename imported files using the file format pattern"
        />
        <SettingField
          label="Write metadata on import"
          type="checkbox"
          checked={(formData.imp_metadata as boolean) ?? false}
          onChange={(v) => onChange("imp_metadata", v as boolean)}
          helpText="Tag imported files with ComicInfo.xml metadata"
        />
        <SettingField
          label="Create series folders"
          type="checkbox"
          checked={(formData.imp_seriesfolders as boolean) ?? false}
          onChange={(v) => onChange("imp_seriesfolders", v as boolean)}
          helpText="Automatically create series folders for imported files"
        />
      </SettingGroup>

      {/* Scheduling */}
      <SettingGroup
        title="Scheduling"
        description="Intervals for automated background tasks (in minutes)"
      >
        <SettingField
          label="Search Interval"
          type="number"
          value={formData.search_interval as number | undefined}
          onChange={(v) =>
            onChange("search_interval", parseInt(v as string) || 360)
          }
          helpText="How often to search for wanted issues (default: 360 min)"
        />
        <SettingField
          label="RSS Check Interval"
          type="number"
          value={formData.rss_check_interval as number | undefined}
          onChange={(v) =>
            onChange("rss_check_interval", parseInt(v as string) || 20)
          }
          helpText="How often to check RSS feeds (default: 20 min)"
        />
        <SettingField
          label="Database Update Interval"
          type="number"
          value={formData.dbupdate_interval as number | undefined}
          onChange={(v) =>
            onChange("dbupdate_interval", parseInt(v as string) || 24)
          }
          helpText="How often to update series metadata from providers (default: 24 hours)"
        />
      </SettingGroup>

      {/* Quality & Organization */}
      <SettingGroup
        title="Quality & Organization"
        description="Additional library management preferences"
      >
        <SettingField
          label="Include annuals"
          type="checkbox"
          checked={(formData.annuals_on as boolean) ?? false}
          onChange={(v) => onChange("annuals_on", v as boolean)}
          helpText="Automatically include annual issues when monitoring series"
        />
        <SettingField
          label="Create weekly folders"
          type="checkbox"
          checked={(formData.weekfolder as boolean) ?? false}
          onChange={(v) => onChange("weekfolder", v as boolean)}
          helpText="Organize downloads into weekly subfolders"
        />
        <SettingField
          label="Enable metadata tagging"
          type="checkbox"
          checked={(formData.enable_meta as boolean) ?? false}
          onChange={(v) => onChange("enable_meta", v as boolean)}
          helpText="Write ComicInfo.xml metadata to downloaded files"
        />
      </SettingGroup>
    </div>
  );
}
