import { useEffect, useMemo, useState } from "react";
import { LoaderCircle, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import {
  useProviderConfig,
  useUpdateNewznabProviders,
} from "@/hooks/useConfig";
import { httpOrigin } from "@/lib/httpOrigin";
import type { NewznabProvider } from "@/types";
import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";
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

type EditableProvider = NewznabProvider & { api_key: string };

function NewznabProviderSettings({
  onDirtyChange,
}: {
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const providerQuery = useProviderConfig();

  if (providerQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 py-4 text-[12px] text-muted-foreground">
        <LoaderCircle className="h-4 w-4 animate-spin" /> Loading indexers…
      </div>
    );
  }

  if (providerQuery.error) {
    return (
      <div role="alert" className="py-3 text-[12px] text-destructive">
        {providerQuery.error.message}
      </div>
    );
  }

  if (!providerQuery.data) return null;

  return (
    <NewznabProviderForm
      key={JSON.stringify(providerQuery.data.newznab)}
      initial={providerQuery.data.newznab}
      onDirtyChange={onDirtyChange}
    />
  );
}

function NewznabProviderForm({
  initial,
  onDirtyChange,
}: {
  initial: { enabled: boolean; providers: NewznabProvider[] };
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const { addToast } = useToast();
  const updateProviders = useUpdateNewznabProviders();
  const [enabled, setEnabled] = useState(initial.enabled);
  const initialProviders = useMemo(
    () => initial.providers.map((provider) => ({ ...provider, api_key: "" })),
    [initial.providers],
  );
  const [providers, setProviders] =
    useState<EditableProvider[]>(initialProviders);
  const isDirty =
    enabled !== initial.enabled ||
    JSON.stringify(providers) !== JSON.stringify(initialProviders);

  useEffect(() => {
    onDirtyChange?.(isDirty);
    return () => onDirtyChange?.(false);
  }, [isDirty, onDirtyChange]);

  const updateProvider = (index: number, patch: Partial<EditableProvider>) => {
    setProviders((current) =>
      current.map((provider, providerIndex) =>
        providerIndex === index ? { ...provider, ...patch } : provider,
      ),
    );
  };

  const addProvider = () => {
    setProviders((current) => [
      ...current,
      {
        name: "",
        host: "",
        verify: true,
        // 7030 is Books/Comics in the standard Newznab category numbering.
        // The old 5030 default was a TV category — harmless while categories
        // were being discarded before reaching the search, and wrong now that
        // they are not.
        categories: "7030",
        rss_uid: "1",
        enabled: true,
        api_key_set: false,
        api_key: "",
      },
    ]);
  };

  const resetProviders = () => {
    setEnabled(initial.enabled);
    setProviders(initialProviders);
  };

  const saveProviders = async () => {
    const incomplete = providers.some(
      (provider) =>
        !provider.name.trim() ||
        !provider.host.trim() ||
        (!provider.api_key_set && !provider.api_key.trim()),
    );
    if (incomplete) {
      addToast({
        type: "error",
        message: "Each indexer needs a name, URL, and API key.",
      });
      return;
    }
    const redirectedSecret = providers.some((provider) => {
      if (!provider.api_key_set || provider.api_key.trim()) return false;
      const original = initial.providers.find(
        (candidate) => candidate.id === provider.id,
      );
      return Boolean(
        original && httpOrigin(original.host) !== httpOrigin(provider.host),
      );
    });
    if (redirectedSecret) {
      addToast({
        type: "error",
        message: "Enter the API key again when changing an indexer server.",
      });
      return;
    }
    try {
      await updateProviders.mutateAsync({ enabled, providers });
      addToast({ type: "success", message: "Search indexers saved" });
    } catch (error) {
      addToast({
        type: "error",
        message:
          error instanceof Error ? error.message : "Failed to save indexers",
      });
    }
  };

  return (
    <div className="space-y-4">
      <SettingField
        label="Enable Newznab indexers"
        type="checkbox"
        checked={enabled}
        onChange={(value) => setEnabled(value as boolean)}
        helpText="At least one enabled indexer is required for Usenet search."
      />

      <p className="text-[12px] text-muted-foreground">
        Indexer edits are saved separately from the page-level settings
        controls.
      </p>

      {providers.length === 0 ? (
        <div className="rounded-[6px] border border-dashed px-4 py-5 text-[12px] text-muted-foreground">
          No Usenet indexers are configured. Add a Newznab-compatible indexer to
          make the NZB route searchable.
        </div>
      ) : (
        <div className="space-y-3">
          {providers.map((provider, index) => {
            const suffix =
              provider.id != null ? `saved-${provider.id}` : `new-${index}`;
            return (
              <article
                key={provider.id ?? `new-${index}`}
                className="rounded-[6px] border p-4"
                style={{ borderColor: "var(--border)" }}
              >
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="font-mono text-[11px] font-semibold uppercase tracking-[0.06em]">
                    Indexer {index + 1}
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Remove indexer ${index + 1}`}
                    onClick={() =>
                      setProviders((current) =>
                        current.filter(
                          (_, providerIndex) => providerIndex !== index,
                        ),
                      )
                    }
                  >
                    <Trash2 />
                  </Button>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <Label htmlFor={`indexer-name-${suffix}`}>
                      Indexer name
                    </Label>
                    <Input
                      id={`indexer-name-${suffix}`}
                      className="mt-1.5"
                      value={provider.name}
                      onChange={(event) =>
                        updateProvider(index, { name: event.target.value })
                      }
                    />
                  </div>
                  <div>
                    <Label htmlFor={`indexer-host-${suffix}`}>
                      Indexer URL
                    </Label>
                    <Input
                      id={`indexer-host-${suffix}`}
                      className="mt-1.5"
                      value={provider.host}
                      placeholder="https://indexer.example/api"
                      onChange={(event) =>
                        updateProvider(index, { host: event.target.value })
                      }
                    />
                  </div>
                  <div>
                    <Label htmlFor={`indexer-key-${suffix}`}>
                      Indexer API key
                    </Label>
                    <Input
                      id={`indexer-key-${suffix}`}
                      className="mt-1.5"
                      type="password"
                      value={provider.api_key}
                      placeholder={
                        provider.api_key_set
                          ? "API key saved (enter a new value to change)"
                          : "Enter the indexer API key"
                      }
                      onChange={(event) =>
                        updateProvider(index, { api_key: event.target.value })
                      }
                    />
                  </div>
                  <div>
                    <Label htmlFor={`indexer-categories-${suffix}`}>
                      Categories
                    </Label>
                    <Input
                      id={`indexer-categories-${suffix}`}
                      className="mt-1.5"
                      value={provider.categories}
                      placeholder="7030"
                      onChange={(event) =>
                        updateProvider(index, {
                          categories: event.target.value,
                        })
                      }
                    />
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      Newznab category IDs, comma-separated. 7030 is
                      Books/Comics.
                    </p>
                  </div>
                  <div>
                    <Label htmlFor={`indexer-rss-uid-${suffix}`}>
                      RSS user ID
                    </Label>
                    <Input
                      id={`indexer-rss-uid-${suffix}`}
                      className="mt-1.5"
                      value={provider.rss_uid ?? ""}
                      placeholder="1"
                      onChange={(event) =>
                        updateProvider(index, {
                          rss_uid: event.target.value,
                        })
                      }
                    />
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      The <code>i=</code> parameter of this indexer&rsquo;s RSS
                      URL. Leave as 1 unless your indexer says otherwise.
                    </p>
                  </div>
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  <SettingField
                    label={`Enable indexer ${index + 1}`}
                    type="checkbox"
                    checked={provider.enabled}
                    onChange={(value) =>
                      updateProvider(index, { enabled: value as boolean })
                    }
                  />
                  <SettingField
                    label={`Verify TLS for indexer ${index + 1}`}
                    type="checkbox"
                    checked={provider.verify}
                    onChange={(value) =>
                      updateProvider(index, { verify: value as boolean })
                    }
                  />
                </div>
              </article>
            );
          })}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button type="button" variant="outline" size="sm" onClick={addProvider}>
          <Plus /> Add indexer
        </Button>
        <div className="flex items-center gap-2">
          {isDirty && (
            <span className="text-[11px] text-muted-foreground">
              Unsaved indexer changes
            </span>
          )}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={!isDirty}
            onClick={resetProviders}
          >
            Reset indexers
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={!isDirty || updateProviders.isPending}
            onClick={() => void saveProviders()}
          >
            {updateProviders.isPending && (
              <LoaderCircle className="animate-spin" />
            )}
            Save indexers
          </Button>
        </div>
      </div>
    </div>
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
      <SettingGroup
        title="Usenet indexers"
        description="Configure the Newznab-compatible sources Comicarr searches before handing an NZB to your download client."
      >
        <NewznabProviderSettings onDirtyChange={onProviderDirtyChange} />
      </SettingGroup>

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
