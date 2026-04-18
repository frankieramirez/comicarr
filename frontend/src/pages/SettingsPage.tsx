import { useState, useEffect, useMemo } from "react";
import { useConfig, useUpdateConfig } from "@/hooks/useConfig";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { GeneralTab } from "@/components/settings/GeneralTab";
import { InterfaceTab } from "@/components/settings/InterfaceTab";
import { ApiTab } from "@/components/settings/ApiTab";
import { SearchTab } from "@/components/settings/SearchTab";
import { DownloadClientsTab } from "@/components/settings/DownloadClientsTab";
import { AiTab } from "@/components/settings/AiTab";
import { NotificationsTab } from "@/components/settings/NotificationsTab";
import { MediaManagementTab } from "@/components/settings/MediaManagementTab";
import { SaveButton } from "@/components/settings/SaveButton";
import PageHeader from "@/components/layout/PageHeader";
import { Kbd } from "@/components/ui/kbd";

type SectionId =
  | "general"
  | "interface"
  | "api"
  | "search"
  | "media"
  | "notifications"
  | "clients"
  | "ai"
  | "about";

const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "general", label: "General" },
  { id: "interface", label: "Interface" },
  { id: "api", label: "API & providers" },
  { id: "search", label: "Search" },
  { id: "media", label: "Media" },
  { id: "notifications", label: "Notifications" },
  { id: "clients", label: "Download clients" },
  { id: "ai", label: "AI" },
  { id: "about", label: "About" },
];

export default function SettingsPage() {
  const { data: config, isLoading, error } = useConfig();
  const updateConfigMutation = useUpdateConfig();
  const { addToast } = useToast();

  const [section, setSection] = useState<SectionId>("general");
  const [formData, setFormData] = useState<Record<string, unknown>>({});
  const [originalData, setOriginalData] = useState<Record<string, unknown>>({});

  useEffect(() => {
    if (config && Object.keys(formData).length === 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Sync external data to local form state
      setFormData(config);
      setOriginalData(config);
    }
  }, [config, formData]);

  const isDirty = useMemo(
    () => JSON.stringify(formData) !== JSON.stringify(originalData),
    [formData, originalData],
  );

  const handleChange = (key: string, value: string | boolean | number) => {
    setFormData((prev) => ({ ...prev, [key]: value }));
  };

  const validateForm = (
    data: Record<string, unknown>,
  ): Record<string, string> => {
    const errors: Record<string, string> = {};
    const comicvineApi = data.comicvine_api as string | undefined;
    const minsize = data.minsize as string | number | undefined;
    const maxsize = data.maxsize as string | number | undefined;
    const comicvineEnabled = (data.comicvine_enabled as boolean) ?? true;
    const mangadexEnabled = (data.mangadex_enabled as boolean) ?? false;

    if (!comicvineEnabled && !mangadexEnabled) {
      errors.comicvine_enabled =
        "At least one content source (Comics or Manga) must be enabled";
    }
    if (comicvineEnabled && comicvineApi && comicvineApi.length !== 40) {
      errors.comicvine_api = "Comic Vine API key must be 40 characters";
    }
    if (data.use_minsize && (!minsize || parseInt(String(minsize)) <= 0)) {
      errors.minsize = "Minimum size must be a positive number";
    }
    if (data.use_maxsize && (!maxsize || parseInt(String(maxsize)) <= 0)) {
      errors.maxsize = "Maximum size must be a positive number";
    }
    if (
      data.use_minsize &&
      data.use_maxsize &&
      parseInt(String(minsize)) >= parseInt(String(maxsize))
    ) {
      errors.minsize = "Minimum size must be less than maximum size";
    }
    return errors;
  };

  const handleSave = async () => {
    const errors = validateForm(formData);
    if (Object.keys(errors).length > 0) {
      addToast({
        type: "error",
        message: `Validation error: ${Object.values(errors)[0]}`,
      });
      return;
    }
    try {
      const saveData = { ...formData };
      if (!saveData.ai_api_key && config?.ai_api_key_set) {
        delete saveData.ai_api_key;
      }
      await updateConfigMutation.mutateAsync(saveData);
      addToast({ type: "success", message: "Settings saved successfully" });
      setOriginalData(formData);
    } catch (err) {
      addToast({
        type: "error",
        message: err instanceof Error ? err.message : "Failed to save settings",
      });
    }
  };

  const handleCancel = () => {
    setFormData(originalData);
    addToast({ type: "info", message: "Changes discarded" });
  };

  if (isLoading) {
    return (
      <div className="p-6">
        <Skeleton className="h-6 w-48 mb-2" />
        <Skeleton className="h-4 w-96 mb-6" />
        <Skeleton className="h-[480px] w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div
          className="rounded-[6px] border p-4"
          style={{
            borderColor:
              "color-mix(in oklab, var(--status-error) 30%, transparent)",
            background: "var(--status-error-bg)",
            color: "var(--status-error)",
          }}
        >
          <div className="font-semibold mb-1">Error loading settings</div>
          <div className="text-[12px]">
            {error.message || "Failed to load configuration."}
          </div>
        </div>
      </div>
    );
  }

  const configPath =
    (config?.config_path as string | undefined) || "/config/config.ini";
  const version = config?.version ? `comicarr v${config.version}` : "comicarr";

  const configData = (config ?? {}) as Record<string, unknown>;
  const tabProps = { config: configData, formData, onChange: handleChange };

  return (
    <div className="h-full flex flex-col page-transition">
      <PageHeader title="Settings" meta={`${version} · config ${configPath}`} />

      <div
        className="grid flex-1 min-h-0"
        style={{ gridTemplateColumns: "220px 1fr" }}
      >
        {/* Left rail */}
        <aside
          className="border-r py-3 px-2 overflow-auto"
          style={{ borderColor: "var(--border)" }}
        >
          {SECTIONS.map((s) => {
            const active = section === s.id;
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => setSection(s.id)}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-[5px] text-[13px] text-left"
                style={{
                  color: active
                    ? "var(--foreground)"
                    : "var(--muted-foreground)",
                  background: active ? "var(--secondary)" : "transparent",
                }}
              >
                <span className="flex-1 truncate">{s.label}</span>
                {active && <Kbd>↵</Kbd>}
              </button>
            );
          })}
        </aside>

        {/* Content panel */}
        <div className="overflow-auto">
          <div className="px-6 py-6 max-w-3xl">
            {section === "general" && <GeneralTab {...tabProps} />}
            {section === "interface" && <InterfaceTab {...tabProps} />}
            {section === "api" && <ApiTab {...tabProps} />}
            {section === "search" && <SearchTab {...tabProps} />}
            {section === "media" && <MediaManagementTab {...tabProps} />}
            {section === "notifications" && <NotificationsTab {...tabProps} />}
            {section === "clients" && <DownloadClientsTab config={formData} />}
            {section === "ai" && <AiTab {...tabProps} />}
            {section === "about" && <AboutSection config={configData} />}
          </div>
        </div>
      </div>

      <SaveButton
        isDirty={isDirty}
        onSave={handleSave}
        onCancel={handleCancel}
        isSaving={updateConfigMutation.isPending}
      />
    </div>
  );
}

function AboutSection({ config }: { config: Record<string, unknown> }) {
  const rows: Array<[string, string]> = [
    ["version", (config.version as string) || "—"],
    [
      "config path",
      (config.config_path as string | undefined) || "/config/config.ini",
    ],
    ["data directory", (config.data_dir as string | undefined) || "—"],
    ["python", (config.python_version as string | undefined) || "—"],
  ];

  return (
    <section>
      <div className="mb-4">
        <div className="text-[13px] font-semibold tracking-tight">About</div>
        <div className="text-[12px] text-muted-foreground mt-0.5">
          Build and environment info.
        </div>
      </div>
      <div
        className="rounded-[6px] border divide-y"
        style={{ borderColor: "var(--border)" }}
      >
        {rows.map(([k, v]) => (
          <div
            key={k}
            className="grid items-center px-3.5 py-2.5 font-mono text-[11.5px]"
            style={{ gridTemplateColumns: "160px 1fr" }}
          >
            <div className="text-muted-foreground tracking-[0.05em] uppercase text-[10px]">
              {k}
            </div>
            <div className="truncate">{v}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
