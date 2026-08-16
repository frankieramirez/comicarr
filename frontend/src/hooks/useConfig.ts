import {
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryResult,
  type UseMutationResult,
} from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import type {
  Config,
  ConfigUpdate,
  NewznabProvider,
  ProviderConfigResponse,
  SearchProviderKind,
  TorznabProvider,
} from "@/types";

interface RegenerateApiKeyResponse {
  success: boolean;
  api_key?: string;
  error?: string;
}

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
      apiRequest("PUT", "/api/config", configData),
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
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async () => {
      const result = await apiRequest<RegenerateApiKeyResponse>(
        "POST",
        "/api/config/api-key/regenerate",
      );
      if (!result.success || !result.api_key) {
        throw new Error(result.error || "Failed to regenerate API key");
      }
      return result.api_key;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });
}

export function useProviderConfig(): UseQueryResult<ProviderConfigResponse> {
  return useQuery({
    queryKey: ["config", "providers"],
    queryFn: () =>
      apiRequest<ProviderConfigResponse>("GET", "/api/config/providers"),
    staleTime: 10 * 60 * 1000,
    retry: 1,
  });
}

export function useUpdateSearchProviders(): UseMutationResult<
  unknown,
  Error,
  {
    type: SearchProviderKind;
    enabled: boolean;
    providers: Array<NewznabProvider | TorznabProvider>;
  }
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ type, enabled, providers }) =>
      apiRequest<unknown>("PUT", "/api/config/providers", {
        type,
        enabled,
        providers,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config", "providers"] });
      queryClient.invalidateQueries({ queryKey: ["acquisition", "health"] });
    },
  });
}
