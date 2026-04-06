import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";

export interface AiActivityEntry {
  id: string;
  timestamp: string;
  feature: string;
  action: string;
  prompt_tokens: number;
  completion_tokens: number;
  success: boolean;
  error_message?: string;
}

export function useAiActivity(limit = 50) {
  return useQuery({
    queryKey: ["ai", "activity", limit],
    queryFn: () =>
      apiRequest<AiActivityEntry[]>("GET", `/api/ai/activity?limit=${limit}`),
    staleTime: 30 * 1000,
  });
}
