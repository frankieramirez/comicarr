import { useState, useEffect, useMemo } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
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
import { AcquisitionHealthTab } from "@/components/settings/AcquisitionHealthTab";
import { AboutTab } from "@/components/settings/AboutTab";
import { LogsTab } from "@/components/settings/LogsTab";
import { SaveButton } from "@/components/settings/SaveButton";
import PageHeader from "@/components/layout/PageHeader";
import { prepareConfigSaveData } from "@/lib/configSave";
import { formatAppVersion } from "@/lib/version";
import { httpOrigin } from "@/lib/httpOrigin";
import { settingsPanelClassName, type SectionId } from "@/lib/settingsPanel";
import type { Config } from "@/types";
import type {
  ReadableConfig,
  SettingsFormData,
  WritableConfig,
} from "@/types/config.generated";

const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "general", label: "General" },
  { id: "interface", label: "Interface" },
  { id: "api", label: "API & providers" },
  { id: "search", label: "Search" },
  { id: "acquisition", label: "Acquisition" },
  { id: "media", label: "Media" },
  { id: "notifications", label: "Notifications" },
  { id: "clients", label: "Download clients" },
  { id: "ai", label: "AI" },
  { id: "logs", label: "Logs" },
  { id: "about", label: "About" },
];

const SECTION_IDS = new Set(SECTIONS.map((s) => s.id));

function parseSectionParam(raw: string | null): SectionId | null {
  if (!raw) return null;
  return SECTION_IDS.has(raw as SectionId) ? (raw as SectionId) : null;
}

export default function SettingsPage() {
  const { data: config, isLoading, error } = useConfig();
  const updateConfigMutation = useUpdateConfig();
  const { addToast } = useToast();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();

  const sectionFromUrl = parseSectionParam(searchParams.get("section"));
  const [section, setSectionState] = useState<SectionId>(
    () => sectionFromUrl ?? "general",
  );
  const [providerDirty, setProviderDirty] = useState(false);

  useEffect(() => {
    if (sectionFromUrl && sectionFromUrl !== section) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- URL is the source of truth for deep links
      setSectionState(sectionFromUrl);
    }
  }, [sectionFromUrl, section]);

  const setSection = (id: SectionId) => {
    if (
      section === "search" &&
      id !== "search" &&
      providerDirty &&
      !window.confirm("Discard unsaved indexer changes?")
    ) {
      return;
    }
    setSectionState(id);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (id === "general") {
          next.delete("section");
        } else {
          next.set("section", id);
        }
        return next;
      },
      { replace: true },
    );
  };

  const [formData, setFormData] = useState<SettingsFormData>({});
  const [originalData, setOriginalData] = useState<SettingsFormData>({});
  const [regeneratedApiKey, setRegeneratedApiKey] = useState<string | null>(
    null,
  );
  useEffect(() => {
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!providerDirty) return;
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [providerDirty]);

  useEffect(() => {
    if (!providerDirty) return;
    const confirmNavigation = (event: MouseEvent) => {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      const target =
        event.target instanceof Element
          ? event.target.closest("a[href]")
          : null;
      if (
        !(target instanceof HTMLAnchorElement) ||
        target.target === "_blank" ||
        target.hasAttribute("download")
      )
        return;
      const url = new URL(target.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      if (
        url.pathname === location.pathname &&
        url.search === location.search &&
        url.hash === location.hash
      )
        return;
      if (!window.confirm("Discard unsaved indexer changes?")) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    document.addEventListener("click", confirmNavigation, true);
    return () => document.removeEventListener("click", confirmNavigation, true);
  }, [location, providerDirty]);

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

  const handleChange = <K extends keyof WritableConfig>(
    key: K,
    value: NonNullable<WritableConfig[K]>,
  ) => {
    setFormData((prev) => ({ ...prev, [key]: value }));
  };

  const validateForm = (data: SettingsFormData): Record<string, string> => {
    const errors: Record<string, string> = {};
    const comicvineApi = data.comicvine_api;
    const minsize = data.minsize;
    const maxsize = data.maxsize;
    const comicvineEnabled = data.comicvine_enabled ?? true;
    const mangadexEnabled = data.mangadex_enabled ?? false;

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
    const sabSelected =
      Number(data.nzb_downloader ?? config?.nzb_downloader ?? 3) === 0;
    if (
      sabSelected &&
      typeof data.sab_host === "string" &&
      data.sab_host.trim()
    ) {
      const nextOrigin = httpOrigin(data.sab_host);
      if (!nextOrigin) {
        errors.sab_host = "SABnzbd URL must use HTTP or HTTPS";
      } else if (
        config?.sab_apikey_set &&
        httpOrigin(config.sab_host) !== nextOrigin &&
        !data.sab_apikey
      ) {
        errors.sab_apikey =
          "Enter the SABnzbd API key again when changing the server";
      }
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
      const saveData = prepareConfigSaveData(formData, config);
      await updateConfigMutation.mutateAsync(saveData);
      addToast({
        type: "success",
        message: providerDirty
          ? "Page settings saved; indexer edits still need Save indexers"
          : "Settings saved successfully",
      });
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
    addToast({
      type: "info",
      message: providerDirty
        ? "Page settings discarded; unsaved indexer edits remain"
        : "Changes discarded",
    });
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

  const configPath = config?.config_path || "/config/config.ini";
  const version = `comicarr ${formatAppVersion()}`;

  const configData: Config = config ?? {};
  const tabProps = {
    config: configData as ReadableConfig,
    formData,
    onChange: handleChange,
  };
  const aboutProps = {
    config: configData,
    formData,
    onChange: handleChange,
  };
  const apiTabProps = {
    ...tabProps,
    regeneratedApiKey,
    onRegeneratedApiKey: setRegeneratedApiKey,
  };

  return (
    <div className="h-full flex flex-col page-transition">
      <PageHeader title="Settings" meta={`${version} · config ${configPath}`} />

      {/* Mobile section chips — horizontal scroll */}
      <div
        className="md:hidden border-b overflow-x-auto"
        style={{ borderColor: "var(--border)" }}
      >
        <div className="flex items-center gap-1.5 px-4 py-2 whitespace-nowrap">
          {SECTIONS.map((s) => {
            const active = section === s.id;
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => setSection(s.id)}
                className="px-2.5 py-1 rounded-full border text-[12px] transition-colors shrink-0"
                style={{
                  borderColor: active ? "var(--primary)" : "var(--border)",
                  color: active ? "var(--primary)" : "var(--muted-foreground)",
                  background: active
                    ? "color-mix(in oklab, var(--primary) 12%, transparent)"
                    : "transparent",
                }}
              >
                {s.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid flex-1 min-h-0 grid-cols-1 md:[grid-template-columns:220px_1fr]">
        {/* Desktop left rail */}
        <aside
          className="hidden md:block border-r py-3 px-2 overflow-auto"
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
              </button>
            );
          })}
        </aside>

        {/* Content panel */}
        <div className="overflow-auto min-w-0">
          <div className={settingsPanelClassName(section)}>
            {section === "general" && <GeneralTab {...tabProps} />}
            {section === "interface" && <InterfaceTab {...tabProps} />}
            {section === "api" && <ApiTab {...apiTabProps} />}
            {section === "search" && (
              <SearchTab
                {...tabProps}
                onProviderDirtyChange={setProviderDirty}
              />
            )}
            {section === "acquisition" && <AcquisitionHealthTab />}
            {section === "media" && <MediaManagementTab {...tabProps} />}
            {section === "notifications" && <NotificationsTab {...tabProps} />}
            {section === "clients" && <DownloadClientsTab {...tabProps} />}
            {section === "ai" && <AiTab {...tabProps} />}
            {section === "logs" && <LogsTab {...tabProps} />}
            {section === "about" && <AboutTab {...aboutProps} />}
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
