import { useState, useEffect, useMemo } from 'react';
import { useConfig, useUpdateConfig } from '@/hooks/useConfig';
import { useToast } from '@/components/ui/toast';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Skeleton } from '@/components/ui/skeleton';
import { GeneralTab } from '@/components/settings/GeneralTab';
import { InterfaceTab } from '@/components/settings/InterfaceTab';
import { ApiTab } from '@/components/settings/ApiTab';
import { SearchTab } from '@/components/settings/SearchTab';
import { DownloadClientsTab } from '@/components/settings/DownloadClientsTab';
import { SaveButton } from '@/components/settings/SaveButton';
import { Settings } from 'lucide-react';

export default function SettingsPage() {
  const { data: config, isLoading, error } = useConfig();
  const updateConfigMutation = useUpdateConfig();
  const { addToast } = useToast();

  const [formData, setFormData] = useState({});
  const [originalData, setOriginalData] = useState({});

  useEffect(() => {
    if (config) {
      setFormData(config);
      setOriginalData(config);
    }
  }, [config]);

  const isDirty = useMemo(() => {
    return JSON.stringify(formData) !== JSON.stringify(originalData);
  }, [formData, originalData]);

  const handleChange = (key, value) => {
    setFormData((prev) => ({ ...prev, [key]: value }));
  };

  const validateForm = (data) => {
    const errors = {};

    // Validate Comic Vine API key (should be 40 characters if provided)
    if (data.comicvine_api && data.comicvine_api.length !== 40) {
      errors.comicvine_api = 'Comic Vine API key must be 40 characters';
    }

    // Validate min/max size
    if (data.use_minsize && (!data.minsize || parseInt(data.minsize) <= 0)) {
      errors.minsize = 'Minimum size must be a positive number';
    }

    if (data.use_maxsize && (!data.maxsize || parseInt(data.maxsize) <= 0)) {
      errors.maxsize = 'Maximum size must be a positive number';
    }

    // Validate min < max if both are enabled
    if (
      data.use_minsize &&
      data.use_maxsize &&
      parseInt(data.minsize) >= parseInt(data.maxsize)
    ) {
      errors.minsize = 'Minimum size must be less than maximum size';
    }

    return errors;
  };

  const handleSave = async () => {
    const errors = validateForm(formData);
    if (Object.keys(errors).length > 0) {
      const errorMessage = Object.values(errors)[0];
      addToast({
        type: 'error',
        message: `Validation error: ${errorMessage}`,
      });
      return;
    }

    try {
      await updateConfigMutation.mutateAsync(formData);
      addToast({
        type: 'success',
        message: 'Settings saved successfully',
      });
      setOriginalData(formData);
    } catch (error) {
      addToast({
        type: 'error',
        message: error.message || 'Failed to save settings',
      });
    }
  };

  const handleCancel = () => {
    setFormData(originalData);
    addToast({
      type: 'info',
      message: 'Changes discarded',
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
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <h3 className="text-red-900 font-semibold mb-2">Error Loading Settings</h3>
          <p className="text-red-700 text-sm">
            {error.message || 'Failed to load configuration. Please try again.'}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="mb-6">
        <div className="flex items-center space-x-3 mb-2">
          <Settings className="h-6 w-6 text-gray-700" />
          <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        </div>
        <p className="text-gray-600">
          Configure Mylar preferences and integrations
        </p>
      </div>

      <Tabs defaultValue="general" className="w-full">
        <TabsList className="mb-6">
          <TabsTrigger value="general">General</TabsTrigger>
          <TabsTrigger value="interface">Interface</TabsTrigger>
          <TabsTrigger value="api">API & Comic Vine</TabsTrigger>
          <TabsTrigger value="search">Search</TabsTrigger>
          <TabsTrigger value="clients">Download Clients</TabsTrigger>
        </TabsList>

        <TabsContent value="general">
          <GeneralTab config={formData} />
        </TabsContent>

        <TabsContent value="interface">
          <InterfaceTab
            config={config}
            formData={formData}
            onChange={handleChange}
          />
        </TabsContent>

        <TabsContent value="api">
          <ApiTab
            config={config}
            formData={formData}
            onChange={handleChange}
          />
        </TabsContent>

        <TabsContent value="search">
          <SearchTab
            config={config}
            formData={formData}
            onChange={handleChange}
          />
        </TabsContent>

        <TabsContent value="clients">
          <DownloadClientsTab config={formData} />
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
