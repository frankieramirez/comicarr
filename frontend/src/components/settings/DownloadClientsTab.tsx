import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";
import type {
  ReadableConfig,
  SettingsFormData,
  WritableConfig,
} from "../../types/config.generated";

interface DownloadClientsTabProps {
  config: ReadableConfig;
  formData: SettingsFormData;
  onChange: <K extends keyof WritableConfig>(
    key: K,
    value: NonNullable<WritableConfig[K]>,
  ) => void;
}

export function DownloadClientsTab({
  config,
  formData,
  onChange,
}: DownloadClientsTabProps) {
  const downloader = Number(formData.nzb_downloader ?? 3);

  return (
    <div className="space-y-6">
      <SettingGroup
        title="Usenet download client"
        description="Choose where NZB files are handed off after an indexer finds a release."
      >
        <SettingField
          label="NZB client"
          type="select"
          value={String(downloader)}
          options={[
            { value: "3", label: "Disabled" },
            { value: "0", label: "SABnzbd" },
            { value: "1", label: "NZBGet" },
            { value: "2", label: "Blackhole" },
          ]}
          onChange={(value) =>
            onChange("nzb_downloader", Number(value) as number)
          }
          helpText="SABnzbd can be configured here. Existing NZBGet and Blackhole settings remain available in config.ini."
        />
      </SettingGroup>

      {downloader === 0 && (
        <SettingGroup
          title="SABnzbd"
          description="Comicarr sends matched NZBs directly to this SABnzbd instance."
        >
          <SettingField
            label="SABnzbd URL"
            value={formData.sab_host ?? ""}
            onChange={(value) => onChange("sab_host", value as string)}
            placeholder="http://sabnzbd:8080"
            helpText="Use the URL Comicarr can reach, including the port."
          />
          <SettingField
            label="SABnzbd API key"
            type="password"
            value={formData.sab_apikey ?? ""}
            onChange={(value) => onChange("sab_apikey", value as string)}
            placeholder={
              config.sab_apikey_set
                ? "API key saved (enter a new value to change)"
                : "Enter the SABnzbd API key"
            }
            helpText="Stored encrypted and never returned by the API."
          />
          <SettingField
            label="Category"
            value={formData.sab_category ?? ""}
            onChange={(value) => onChange("sab_category", value as string)}
            placeholder="comics"
          />
          <SettingField
            label="Download directory"
            value={formData.sab_directory ?? ""}
            onChange={(value) => onChange("sab_directory", value as string)}
            placeholder="/downloads"
            helpText="Required when Comicarr performs post-processing. The path must exist inside the Comicarr environment."
          />
          <SettingField
            label="Verify SABnzbd TLS certificate"
            type="checkbox"
            checked={Boolean(formData.sab_verify)}
            onChange={(value) => onChange("sab_verify", value as boolean)}
          />
        </SettingGroup>
      )}

      {downloader !== 0 && downloader !== 3 && (
        <SettingGroup
          title={config.nzb_downloader_label || "Existing NZB client"}
          description="This client remains active, but its advanced fields are not yet editable here."
        >
          <p className="text-[12px] text-muted-foreground">
            Use the config file shown in the Settings header to change this
            client’s connection details.
          </p>
        </SettingGroup>
      )}

      <SettingGroup
        title="Completed downloads"
        description="The Folder Monitor checks these folders for finished downloads and imports them."
      >
        <SettingField
          label="Additional monitored folders"
          type="textarea"
          value={formData.additional_check_folders || ""}
          onChange={(v) => onChange("additional_check_folders", v as string)}
          helpText={
            config.check_folder
              ? `Scanned after the main monitored folder, ${config.check_folder}. One server path per line. In Docker, use the path inside the container.`
              : "Scanned after the main monitored folder, which is set as CHECK_FOLDER in the config file. These folders are ignored until it is set."
          }
          placeholder="/downloads/Magazines"
        />
      </SettingGroup>
    </div>
  );
}
