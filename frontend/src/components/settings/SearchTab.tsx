import { useEffect, useState, type ReactNode } from "react";
import { LoaderCircle } from "lucide-react";
import { useProviderConfig } from "@/hooks/useConfig";
import type { ProviderConfigResponse } from "@/types";
import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";
import { SearchProviderEditor } from "./SearchProviderEditor";
import type {
  ReadableConfig,
  SettingsFormData,
  WritableConfig,
} from "../../types/config.generated";

interface SearchTabProps {
  config: ReadableConfig;
  formData: SettingsFormData;
  onChange: <K extends keyof WritableConfig>(
    key: K,
    value: NonNullable<WritableConfig[K]>,
  ) => void;
  onProviderDirtyChange?: (dirty: boolean) => void;
}

const EMPTY_GROUP: ProviderConfigResponse["newznab"] = {
  enabled: false,
  providers: [],
};

function ProviderQueryStatus({
  isLoading,
  error,
  children,
}: {
  isLoading: boolean;
  error: Error | null;
  children: ReactNode;
}) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-4 text-[12px] text-muted-foreground">
        <LoaderCircle className="h-4 w-4 animate-spin" /> Loading indexers…
      </div>
    );
  }

  if (error) {
    return (
      <div role="alert" className="py-3 text-[12px] text-destructive">
        {error.message}
      </div>
    );
  }

  return children;
}

function SearchProviderSettings({
  onDirtyChange,
}: {
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const providerQuery = useProviderConfig();
  const [newznabDirty, setNewznabDirty] = useState(false);
  const [torznabDirty, setTorznabDirty] = useState(false);
  const dirty = newznabDirty || torznabDirty;

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    return () => onDirtyChange?.(false);
  }, [onDirtyChange]);

  const newznab = providerQuery.data?.newznab ?? EMPTY_GROUP;
  const torznab = providerQuery.data?.torznab ?? EMPTY_GROUP;
  const queryError =
    providerQuery.error instanceof Error ? providerQuery.error : null;

  return (
    <>
      <SettingGroup
        title="Usenet indexers"
        description="Configure the Newznab-compatible sources Comicarr searches before handing an NZB to your download client."
      >
        <ProviderQueryStatus
          isLoading={providerQuery.isLoading}
          error={queryError}
        >
          {providerQuery.data ? (
            <SearchProviderEditor
              key={`newznab:${JSON.stringify(newznab)}`}
              kind="newznab"
              initial={newznab}
              onDirtyChange={setNewznabDirty}
            />
          ) : null}
        </ProviderQueryStatus>
      </SettingGroup>

      <SettingGroup
        title="Torrent indexers"
        description="Configure the Torznab-compatible sources Comicarr searches before handing a torrent to your download client."
      >
        <ProviderQueryStatus
          isLoading={providerQuery.isLoading}
          error={queryError}
        >
          {providerQuery.data ? (
            <SearchProviderEditor
              key={`torznab:${JSON.stringify(torznab)}`}
              kind="torznab"
              initial={torznab}
              onDirtyChange={setTorznabDirty}
            />
          ) : null}
        </ProviderQueryStatus>
      </SettingGroup>
    </>
  );
}

export function SearchTab({
  formData,
  onChange,
  onProviderDirtyChange,
}: SearchTabProps) {
  const qualityOptions = [
    { value: "0", label: "Any Quality" },
    { value: "1", label: "HD Only" },
    { value: "2", label: "Web-DL Only" },
  ];

  return (
    <div className="space-y-6">
      <SearchProviderSettings onDirtyChange={onProviderDirtyChange} />

      <SettingGroup
        title="Quality Settings"
        description="Configure preferred quality for downloads"
      >
        <SettingField
          label="Preferred Quality"
          value={String(formData.preferred_quality ?? "")}
          type="select"
          options={qualityOptions}
          onChange={(value) =>
            onChange("preferred_quality", parseInt(value as string) || 0)
          }
          helpText="Filter search results by quality preference"
        />
      </SettingGroup>

      <SettingGroup
        title="File Size Constraints"
        description="Set minimum and maximum file size limits for downloads"
      >
        <SettingField
          label="Enable Minimum Size"
          type="checkbox"
          checked={formData.use_minsize}
          onChange={(checked) => onChange("use_minsize", checked as boolean)}
          helpText="Reject downloads smaller than the minimum size"
        />
        {Boolean(formData.use_minsize) && (
          <SettingField
            label="Minimum Size (MB)"
            value={formData.minsize}
            type="number"
            onChange={(value) => onChange("minsize", value as string)}
            placeholder="e.g., 10"
            helpText="Minimum file size in megabytes"
          />
        )}
        <SettingField
          label="Enable Maximum Size"
          type="checkbox"
          checked={formData.use_maxsize}
          onChange={(checked) => onChange("use_maxsize", checked as boolean)}
          helpText="Reject downloads larger than the maximum size"
        />
        {Boolean(formData.use_maxsize) && (
          <SettingField
            label="Maximum Size (MB)"
            value={formData.maxsize}
            type="number"
            onChange={(value) => onChange("maxsize", value as string)}
            placeholder="e.g., 500"
            helpText="Maximum file size in megabytes"
          />
        )}
      </SettingGroup>
    </div>
  );
}
