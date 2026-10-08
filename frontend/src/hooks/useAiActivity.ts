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

interface AiActivityResponse {
  entries: AiActivityEntry[];
}

export function useAiActivity(limit = 50, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ["ai", "activity", limit],
    queryFn: () =>
      apiRequest<AiActivityResponse>("GET", `/api/ai/activity?limit=${limit}`),
    select: (data) => data.entries ?? [],
    staleTime: 30 * 1000,
    enabled: options?.enabled ?? true,
  });
}
