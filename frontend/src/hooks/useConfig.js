import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiCall } from '@/lib/api';
import { useToast } from '@/components/ui/toast';

export function useConfig() {
  return useQuery({
    queryKey: ['config'],
    queryFn: async () => {
      const data = await apiCall('getConfig');
      return data;
    },
    staleTime: 10 * 60 * 1000, // 10 minutes
    retry: 1,
  });
}

export function useUpdateConfig() {
  const queryClient = useQueryClient();
  const { addToast } = useToast();

  return useMutation({
    mutationFn: async (configData) => {
      const data = await apiCall('setConfig', configData);
      return data;
    },
    onSuccess: () => {
      // Invalidate and refetch config
      queryClient.invalidateQueries({ queryKey: ['config'] });
    },
    onError: (error) => {
      addToast({
        type: 'error',
        message: error.message || 'Failed to update configuration',
      });
    },
  });
}

export function useGenerateApiKey() {
  const updateConfig = useUpdateConfig();
  const { addToast } = useToast();

  return useMutation({
    mutationFn: async () => {
      // Generate a new UUID for the API key
      const newApiKey = crypto.randomUUID();

      // Update the config with the new API key
      await updateConfig.mutateAsync({ api_key: newApiKey });

      return newApiKey;
    },
    onSuccess: () => {
      addToast({
        type: 'success',
        message: 'API key regenerated successfully',
      });
    },
    onError: (error) => {
      addToast({
        type: 'error',
        message: error.message || 'Failed to regenerate API key',
      });
    },
  });
}
