import {
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryResult,
  type UseMutationResult,
} from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import type { Config, ConfigUpdate } from "@/types";

export function useConfig(): UseQueryResult<Config> {
  return useQuery({
    queryKey: ["config"],
    queryFn: () => apiRequest<Config>("GET", "/api/config"),
    staleTime: 10 * 60 * 1000, // 10 minutes
    retry: 1,
  });
}

export function useUpdateConfig(): UseMutationResult<
  unknown,
  Error,
  ConfigUpdate
> {
  const queryClient = useQueryClient();
  const { addToast } = useToast();

  return useMutation({
    mutationFn: (configData: ConfigUpdate) =>
      apiRequest("PUT", "/api/config", configData as Record<string, unknown>),
    onSuccess: () => {
      // Invalidate and refetch config
      queryClient.invalidateQueries({ queryKey: ["config"] });
    },
    onError: (error: Error) => {
      addToast({
        type: "error",
        message: error.message || "Failed to update configuration",
      });
    },
  });
}

export function useGenerateApiKey(): UseMutationResult<string, Error, void> {
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
        type: "success",
        message: "API key regenerated successfully",
      });
    },
    onError: (error: Error) => {
      addToast({
        type: "error",
        message: error.message || "Failed to regenerate API key",
      });
    },
  });
}
