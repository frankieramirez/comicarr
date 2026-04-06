import { useState, useEffect, useMemo } from "react";
import { useConfig, useUpdateConfig } from "@/hooks/useConfig";
import { useToast } from "@/components/ui/toast";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { GeneralTab } from "@/components/settings/GeneralTab";
import { InterfaceTab } from "@/components/settings/InterfaceTab";
import { ApiTab } from "@/components/settings/ApiTab";
import { SearchTab } from "@/components/settings/SearchTab";
import { DownloadClientsTab } from "@/components/settings/DownloadClientsTab";
import { AiTab } from "@/components/settings/AiTab";
import { SaveButton } from "@/components/settings/SaveButton";
import { Settings } from "lucide-react";

export default function SettingsPage() {
  const { data: config, isLoading, error } = useConfig();
  const updateConfigMutation = useUpdateConfig();
  const { addToast } = useToast();

  const [formData, setFormData] = useState<Record<string, unknown>>({});
  const [originalData, setOriginalData] = useState<Record<string, unknown>>({});

  // Initialize form data when config is loaded
  useEffect(() => {
    if (config && Object.keys(formData).length === 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Sync external data to local form state
      setFormData(config);

      setOriginalData(config);
    }
  }, [config, formData]);

  const isDirty = useMemo(() => {
    return JSON.stringify(formData) !== JSON.stringify(originalData);
  }, [formData, originalData]);

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

    // At least one content source must be enabled
    if (!comicvineEnabled && !mangadexEnabled) {
      errors.comicvine_enabled =
        "At least one content source (Comics or Manga) must be enabled";
    }

    // Validate Comic Vine API key (should be 40 characters if provided)
    if (comicvineEnabled && comicvineApi && comicvineApi.length !== 40) {
      errors.comicvine_api = "Comic Vine API key must be 40 characters";
    }

    // Validate min/max size
    if (data.use_minsize && (!minsize || parseInt(String(minsize)) <= 0)) {
      errors.minsize = "Minimum size must be a positive number";
    }

    if (data.use_maxsize && (!maxsize || parseInt(String(maxsize)) <= 0)) {
      errors.maxsize = "Maximum size must be a positive number";
    }

    // Validate min < max if both are enabled
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
      const errorMessage = Object.values(errors)[0];
      addToast({
        type: "error",
        message: `Validation error: ${errorMessage}`,
      });
      return;
    }

    try {
      await updateConfigMutation.mutateAsync(formData);
      addToast({
        type: "success",
        message: "Settings saved successfully",
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
      message: "Changes discarded",
    });
  };

  if (isLoading) {
    return (
      <div className="p-6">
        <div className="mb-6">
          <Skeleton className="h-8 w-48 mb-2" />
          <Skeleton className="h-4 w-96" />
        </div>
        <div className="space-y-4">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-[var(--status-error-bg)] border border-[var(--status-error)] rounded-lg p-4">
          <h3 className="text-destructive font-semibold mb-2">
            Error Loading Settings
          </h3>
          <p className="text-destructive text-sm">
            {error.message || "Failed to load configuration. Please try again."}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 page-transition">
      <div className="mb-6">
        <div className="flex items-center space-x-3 mb-2">
          <Settings className="h-6 w-6 text-muted-foreground" />
          <h1 className="text-2xl font-bold text-foreground">Settings</h1>
          {config?.version && (
            <span className="text-sm text-muted-foreground font-normal">
              v{config.version}
            </span>
          )}
        </div>
        <p className="text-muted-foreground">
          Configure Comicarr preferences and integrations
        </p>
      </div>

      <Tabs defaultValue="general" className="w-full">
        <TabsList className="mb-6">
          <TabsTrigger value="general">General</TabsTrigger>
          <TabsTrigger value="interface">Interface</TabsTrigger>
          <TabsTrigger value="api">API & Providers</TabsTrigger>
          <TabsTrigger value="search">Search</TabsTrigger>
          <TabsTrigger value="clients">Download Clients</TabsTrigger>
          <TabsTrigger value="ai">AI</TabsTrigger>
        </TabsList>

        <TabsContent value="general">
          <GeneralTab config={formData} />
        </TabsContent>

        <TabsContent value="interface">
          <InterfaceTab
            config={(config ?? {}) as Record<string, unknown>}
            formData={formData}
            onChange={handleChange}
          />
        </TabsContent>

        <TabsContent value="api">
          <ApiTab
            config={(config ?? {}) as Record<string, unknown>}
            formData={formData}
            onChange={handleChange}
          />
        </TabsContent>

        <TabsContent value="search">
          <SearchTab
            config={(config ?? {}) as Record<string, unknown>}
            formData={formData}
            onChange={handleChange}
          />
        </TabsContent>

        <TabsContent value="clients">
          <DownloadClientsTab config={formData} />
        </TabsContent>

        <TabsContent value="ai">
          <AiTab
            config={(config ?? {}) as Record<string, unknown>}
            formData={formData}
            onChange={handleChange}
          />
        </TabsContent>
      </Tabs>

      <SaveButton
        isDirty={isDirty}
        onSave={handleSave}
        onCancel={handleCancel}
        isSaving={updateConfigMutation.isPending}
      />

      {isDirty && <div className="h-20" />}
    </div>
  );
}
