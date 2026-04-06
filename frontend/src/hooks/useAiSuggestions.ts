import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";

export interface PullSuggestion {
  comic_name: string;
  publisher: string;
  reason: string;
  resolved_comic_id: string | null;
}

interface SuggestionsResponse {
  suggestions: PullSuggestion[];
}

/**
 * Fetch AI-generated pull list suggestions.
 * Only fetches when AI is configured (enabled flag).
 */
export function useAiSuggestions(enabled: boolean = true) {
  return useQuery({
    queryKey: ["ai", "suggestions"],
    queryFn: () =>
      apiRequest<SuggestionsResponse>("GET", "/api/ai/suggestions"),
    select: (data) => data.suggestions,
    enabled,
    staleTime: 5 * 60 * 1000,
    refetchInterval: 10 * 60 * 1000,
  });
}
