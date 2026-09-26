import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";

export interface SeriesRecommendation {
  comic_name: string;
  publisher: string | null;
  reason: string;
  because_of: string | null;
  comicid: string | null;
  comicyear: string | null;
  issues: number | null;
  comicimage: string | null;
}

interface RecommendationsResponse {
  recommendations: SeriesRecommendation[];
}

/**
 * Fetch cached AI "because you read X" series recommendations.
 * Only fetches when AI is configured (enabled flag).
 */
export function useAiRecommendations(enabled: boolean = true) {
  return useQuery({
    queryKey: ["ai", "recommendations"],
    queryFn: () =>
      apiRequest<RecommendationsResponse>("GET", "/api/ai/recommendations"),
    select: (data) => data.recommendations,
    enabled,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Regenerate recommendations on demand; the response replaces the cache.
 */
export function useRefreshRecommendations(): UseMutationResult<
  RecommendationsResponse,
  Error,
  void
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () =>
      apiRequest<RecommendationsResponse>(
        "POST",
        "/api/ai/recommendations/refresh",
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(["ai", "recommendations"], data);
    },
  });
}
