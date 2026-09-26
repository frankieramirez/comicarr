import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
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

const recommendationsKey = ["ai", "recommendations"] as const;

export function removeRecommendation(
  queryClient: QueryClient,
  comicId: string,
) {
  queryClient.setQueryData<RecommendationsResponse>(
    recommendationsKey,
    (current) =>
      current
        ? {
            ...current,
            recommendations: current.recommendations.filter(
              (recommendation) => recommendation.comicid !== comicId,
            ),
          }
        : current,
  );
}

export function restoreRecommendation(
  queryClient: QueryClient,
  recommendation: SeriesRecommendation,
) {
  queryClient.setQueryData<RecommendationsResponse>(
    recommendationsKey,
    (current) => {
      if (
        !current ||
        current.recommendations.some(
          (item) => item.comicid === recommendation.comicid,
        )
      )
        return current;
      return {
        ...current,
        recommendations: [...current.recommendations, recommendation],
      };
    },
  );
}

/**
 * Fetch cached AI "because you read X" series recommendations.
 * Only fetches when AI is configured (enabled flag).
 */
export function useAiRecommendations(enabled: boolean = true) {
  return useQuery({
    queryKey: recommendationsKey,
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
      queryClient.setQueryData(recommendationsKey, data);
    },
  });
}
