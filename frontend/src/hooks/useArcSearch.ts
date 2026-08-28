import {
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryResult,
  type UseMutationResult,
} from "@tanstack/react-query";
import { apiRequest, ApiError } from "@/lib/api";
import type { ArcSearchResult } from "@/types";

interface RawArcSearchResult {
  comicid?: string;
  cvarcid?: string;
  name?: string;
  publisher?: string | null;
  issues?: string | number | null;
  description?: string | null;
  comicimage?: string | null;
  comicthumb?: string | null;
  image?: string | null;
  arclist?: string | null;
  haveit?: string | null;
  [key: string]: unknown;
}

type RawArcSearchResponse =
  | RawArcSearchResult[]
  | {
      results?: RawArcSearchResult[];
    };

function normalizeArcSearchResults(
  data: RawArcSearchResponse,
): ArcSearchResult[] {
  const rows = Array.isArray(data) ? data : (data.results ?? []);
  return rows.map((row) => {
    const cvarcid = String(row.cvarcid ?? row.comicid ?? "");
    return {
      id: cvarcid,
      name: row.name ?? "",
      publisher: row.publisher ?? null,
      issues: String(row.issues ?? "?"),
      description: row.description ?? null,
      image: row.image || row.comicimage || row.comicthumb || null,
      cvarcid,
      arclist: row.arclist ?? null,
      haveit: row.haveit ?? null,
    };
  });
}

/**
 * Search for story arcs by name (ComicVine)
 */
export function useFindStoryArc(
  query: string,
): UseQueryResult<ArcSearchResult[]> {
  return useQuery({
    queryKey: ["arcSearch", query],
    queryFn: async () => {
      try {
        const data = await apiRequest<RawArcSearchResponse>(
          "POST",
          "/api/search/comics",
          {
            name: query,
            type: "story_arc",
          },
        );
        return normalizeArcSearchResults(data);
      } catch (error) {
        if (
          error instanceof ApiError &&
          /no results/i.test(error.userMessage)
        ) {
          return [];
        }
        throw error;
      }
    },
    enabled: !!query && query.trim().length > 2,
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
