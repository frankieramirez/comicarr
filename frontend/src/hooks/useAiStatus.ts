import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";

export interface AiStatusResponse {
  configured: boolean;
  circuit_state: string;
  today_tokens: number;
  today_requests: number;
  daily_limit: number;
  rpm_limit: number;
}

export function useAiStatus() {
  return useQuery({
    queryKey: ["ai", "status"],
    queryFn: () => apiRequest<AiStatusResponse>("GET", "/api/ai/status"),
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
  });
}
