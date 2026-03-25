import {
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryResult,
  type UseMutationResult,
} from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import type { ArcSearchResult } from "@/types";

/**
 * Search for story arcs by name (ComicVine)
 */
export function useFindStoryArc(
  query: string,
): UseQueryResult<ArcSearchResult[]> {
  return useQuery({
    queryKey: ["arcSearch", query],
    queryFn: () =>
      apiRequest<ArcSearchResult[]>("POST", "/api/search/comics", {
        name: query,
        type: "story_arc",
      }),
    enabled: !!query && query.length > 2,
    staleTime: 10 * 60 * 1000,
  });
}

/**
 * Add a story arc from ComicVine search results
 */
interface AddArcParams {
  arcid: string;
  storyarcname: string;
  storyarcissues: number;
  arclist: string;
  cvarcid: string;
}

export function useAddStoryArc(): UseMutationResult<
  unknown,
  Error,
  AddArcParams
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (params: AddArcParams) =>
      apiRequest("POST", "/api/storyarcs", { ...params }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["storyArcs"] });
    },
  });
}
