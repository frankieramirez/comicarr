import { ph, t } from "@lingui/core/macro";
import { useState, useEffect, useMemo } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { useConfig, useUpdateConfig } from "@/hooks/useConfig";
import { useToast } from "@/components/ui/toast";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import { Skeleton } from "@/components/ui/skeleton";
import { GeneralTab } from "@/components/settings/GeneralTab";
import { InterfaceTab } from "@/components/settings/InterfaceTab";
import { ApiTab } from "@/components/settings/ApiTab";
import { SearchTab } from "@/components/settings/SearchTab";
import { DownloadClientsTab } from "@/components/settings/DownloadClientsTab";
import { hostKey } from "@/lib/downloadClients";
import { AiTab } from "@/components/settings/AiTab";
import { AgentsTab } from "@/components/settings/AgentsTab";
import { NotificationsTab } from "@/components/settings/NotificationsTab";
import { MediaManagementTab } from "@/components/settings/MediaManagementTab";
import { AcquisitionHealthTab } from "@/components/settings/AcquisitionHealthTab";
import { AboutTab } from "@/components/settings/AboutTab";
import { LogsTab } from "@/components/settings/LogsTab";
import { SaveButton } from "@/components/settings/SaveButton";
import PageHeader from "@/components/layout/PageHeader";
import { ToggleChip } from "@/components/ui/toggle-chip";
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

/** The sub-nav, grouped by what the operator is trying to do. */
const SECTION_GROUPS = (): {
  label: string;
  sections: { id: SectionId; label: string }[];
}[] => [
  {
    label: t`Library`,
    sections: [{ id: "media", label: t`Folders and naming` }],
  },
  {
    label: t`Getting files`,
    sections: [
      { id: "search", label: t`Indexers and search` },
      { id: "clients", label: t`Download clients` },
      { id: "acquisition", label: t`Acquisition health` },
    ],
  },
  {
    label: t`Metadata`,
    sections: [{ id: "api", label: t`Sources and keys` }],
  },
  {
    label: t`You`,
    sections: [
      { id: "notifications", label: t`Notifications` },
      { id: "interface", label: t`Interface` },
      { id: "ai", label: t`AI` },
    ],
  },
  {
    label: t`System`,
    sections: [
      { id: "general", label: t`General` },
      { id: "agents", label: t`Agents (MCP)` },
      { id: "logs", label: t`Logs` },
      { id: "about", label: t`About` },
    ],
  },
];

const SECTIONS = () => SECTION_GROUPS().flatMap((group) => group.sections);

const SECTION_IDS = new Set(SECTIONS().map((s) => s.id));

function parseSectionParam(raw: string | null): SectionId | null {
  if (!raw) return null;
  return SECTION_IDS.has(raw as SectionId) ? (raw as SectionId) : null;
}

export default function SettingsPage() {
  const { data: config, isLoading, error, refetch, isFetching } = useConfig();
  const updateConfigMutation = useUpdateConfig();
  const { addToast } = useToast();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();

  // The URL is the only source of truth for the open section. Keeping a
  // second copy in state raced with it: a click could set state, then an
  // effect saw the not-yet-updated URL and put the old section back (#1494).
  const section: SectionId =
    parseSectionParam(searchParams.get("section")) ?? "general";
  const [providerDirty, setProviderDirty] = useState(false);

  const setSection = (id: SectionId) => {
    if (
      section === "search" &&
      id !== "search" &&
      providerDirty &&
      !window.confirm(t`Discard unsaved indexer changes?`)
    ) {
      return;
    }
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
      if (!window.confirm(t`Discard unsaved indexer changes?`)) {
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
      errors.comicvine_enabled = t`At least one content source (Comics or Manga) must be enabled`;
    }
    if (comicvineEnabled && comicvineApi && comicvineApi.length !== 40) {
      errors.comicvine_api = t`Comic Vine API key must be 40 characters`;
    }
    if (data.use_minsize && (!minsize || parseInt(String(minsize)) <= 0)) {
      errors.minsize = t`Minimum size must be a positive number`;
    }
    if (data.use_maxsize && (!maxsize || parseInt(String(maxsize)) <= 0)) {
      errors.maxsize = t`Maximum size must be a positive number`;
    }
    if (
      data.use_minsize &&
      data.use_maxsize &&
      parseInt(String(minsize)) >= parseInt(String(maxsize))
    ) {
      errors.minsize = t`Minimum size must be less than maximum size`;
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
        errors.sab_host = t`SABnzbd URL must use HTTP or HTTPS`;
      } else if (
        config?.sab_apikey_set &&
        httpOrigin(config.sab_host) !== nextOrigin &&
        !data.sab_apikey
      ) {
        errors.sab_apikey = t`Enter the SABnzbd API key again when changing the server`;
      }
    }
    const clientSecrets = [
      [
        "qbittorrent_host",
        "qbittorrent_password",
        "qbittorrent_password_set",
        "qBittorrent",
      ],
      ["nzbget_host", "nzbget_password", "nzbget_password_set", "NZBGet"],
      ["deluge_host", "deluge_password", "deluge_password_set", t`Deluge`],
      [
        "transmission_host",
        "transmission_password",
        "transmission_password_set",
        t`Transmission`,
      ],
    ] as const;
    for (const [hostField, secretField, setField, label] of clientSecrets) {
      const next = data[hostField];
      if (
        typeof next === "string" &&
        config?.[setField] &&
        hostKey(next) !== hostKey(config[hostField] as string | undefined) &&
        !data[secretField]
      ) {
        errors[secretField] =
          t`Enter the ${label} password again when changing the server`;
      }
    }
    return errors;
  };

  const handleSave = async () => {
    const errors = validateForm(formData);
    if (Object.keys(errors).length > 0) {
      addToast({
        type: "error",
        message: t`Validation error: ${ph({ error: Object.values(errors)[0] })}`,
      });
      return;
    }
    try {
      const saveData = prepareConfigSaveData(formData, config);
      await updateConfigMutation.mutateAsync(saveData);
      addToast({
        type: "success",
        message: providerDirty
          ? t`Page settings saved; indexer edits still need Save indexers`
          : t`Settings saved successfully`,
      });
      setOriginalData(formData);
    } catch {
      // useUpdateConfig already shows the error; a second toast here
      // doubled every failed save (#1502).
    }
  };

  const handleCancel = () => {
    setFormData(originalData);
    addToast({
      type: "info",
      message: providerDirty
        ? t`Page settings discarded; unsaved indexer edits remain`
        : t`Changes discarded`,
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
        <ErrorDisplay
          error={error}
          title={t`Unable to load settings`}
          onRetry={() => {
            void refetch();
          }}
          isRetrying={isFetching}
        />
      </div>
    );
  }

  const configPath = config?.config_path || "/config/config.ini";
  const version = formatAppVersion();

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
      <PageHeader
        title={t`Settings`}
        meta={
          <span className="font-mono text-xs">
            {version} · {configPath}
          </span>
        }
      />

      {/* Mobile section chips — horizontal scroll */}
      <div className="md:hidden border-b border-border-subtle overflow-x-auto">
        <div
          role="group"
          aria-label={t`Settings sections`}
          className="flex items-center gap-1.5 px-4 pb-2 whitespace-nowrap"
        >
          {SECTIONS().map((s) => (
            <ToggleChip
              key={s.id}
              pressed={section === s.id}
              onPressedChange={() => setSection(s.id)}
              size="md"
            >
              {s.label}
            </ToggleChip>
          ))}
        </div>
      </div>

      <div className="grid flex-1 min-h-0 grid-cols-1 md:[grid-template-columns:240px_1fr]">
        {/* Desktop left rail */}
        <nav
          aria-label={t`Settings sections`}
          className="hidden md:block overflow-auto pb-8 ps-8 pe-4"
        >
          {SECTION_GROUPS().map((group) => (
            <div key={group.label} className="mb-4">
              <div className="px-2.5 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">
                {group.label}
              </div>
              {group.sections.map((s) => {
                const active = section === s.id;
                return (
                  <button
                    key={s.id}
                    type="button"
                    aria-current={active ? "page" : undefined}
                    onClick={() => setSection(s.id)}
                    className={`flex h-8 w-full items-center rounded-control px-2.5 text-start text-[13px] ${
                      active
                        ? "bg-surface-2 font-medium text-foreground"
                        : "text-foreground-2 hover:bg-surface-1 hover:text-foreground"
                    }`}
                  >
                    <span className="flex-1 truncate">{s.label}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

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
            {section === "agents" && <AgentsTab {...tabProps} />}
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
