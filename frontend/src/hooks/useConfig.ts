import { t } from "@lingui/core/macro";
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
  ProviderOrderResponse,
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
      queryClient.invalidateQueries({ queryKey: ["config"] });
      // A saved client host adds a connection the Test button waits for;
      // without this it stayed disabled until a reload (#1502).
      queryClient.invalidateQueries({ queryKey: ["system", "connections"] });
    },
    onError: (error: Error) => {
      addToast({
        type: "error",
        message: error.message || t`Failed to update configuration`,
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
      queryClient.invalidateQueries({ queryKey: ["config", "provider-order"] });
      queryClient.invalidateQueries({ queryKey: ["acquisition", "health"] });
    },
  });
}

export function useProviderOrder(): UseQueryResult<ProviderOrderResponse> {
  return useQuery({
    queryKey: ["config", "provider-order"],
    queryFn: () =>
      apiRequest<ProviderOrderResponse>("GET", "/api/config/provider-order"),
    retry: 1,
  });
}

export function useUpdateProviderOrder(): UseMutationResult<
  ProviderOrderResponse,
  Error,
  string[]
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (order) =>
      apiRequest<ProviderOrderResponse>("PUT", "/api/config/provider-order", {
        order,
      }),
    onSuccess: async (data) => {
      // A read that started before the save must not land after it and
      // put the old order back in the cache.
      await queryClient.cancelQueries({
        queryKey: ["config", "provider-order"],
      });
      queryClient.setQueryData(["config", "provider-order"], {
        providers: data.providers,
      });
    },
  });
}
