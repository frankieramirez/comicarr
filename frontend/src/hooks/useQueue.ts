import {
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryResult,
  type UseMutationResult,
} from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import type {
  ForceSearchResult,
  WantedIssue,
  UpcomingIssue,
  PaginationMeta,
  SearchMissingResult,
  WantedBucket,
  WantedSeriesResponse,
} from "@/types";

interface WantedResponse {
  issues: WantedIssue[];
  pagination: PaginationMeta;
}

interface WantedSearchPreview {
  preview_token: string;
  fingerprint: string;
}

/**
 * Outcome of a bulk issue mutation. The requests run sequentially, so a failure
 * partway through leaves earlier issues already applied -- callers need to know
 * which ids landed rather than treating the whole batch as failed.
 */
export interface BulkIssueResult {
  succeeded: string[];
  failed: { id: string; error: string }[];
}

/**
 * Turns a bulk outcome into what the page should show and keep selected, so
 * both queue pages report partial failures the same way: the ids that failed
 * stay selected and a retry does not repeat the requests that already landed.
 */
export function describeBulkResult(
  { succeeded, failed }: BulkIssueResult,
  verb: string,
  failureVerb: string,
): { type: "success" | "info" | "error"; message: string; keep: string[] } {
  const total = succeeded.length + failed.length;
  if (failed.length === 0) {
    return {
      type: "success",
      message: `${succeeded.length} issue${succeeded.length !== 1 ? "s" : ""} ${verb}`,
      keep: [],
    };
  }
  return {
    type: succeeded.length > 0 ? "info" : "error",
    message:
      succeeded.length > 0
        ? `${succeeded.length} of ${total} issues ${verb} — ${failed.length} failed: ${failed[0].error}`
        : `Failed to ${failureVerb} issues: ${failed[0].error}`,
    keep: failed.map(({ id }) => id),
  };
}

export async function applySequentially(
  issueIds: string[],
  action: (id: string) => Promise<unknown>,
): Promise<BulkIssueResult> {
  const result: BulkIssueResult = { succeeded: [], failed: [] };
  for (const id of issueIds) {
    try {
      await action(id);
      result.succeeded.push(id);
    } catch (err) {
      result.failed.push({
        id,
        error: err instanceof Error ? err.message : "Unknown error",
      });
    }
  }
  return result;
}

export function useUpcoming(
  includeDownloaded = false,
  week: { week: string; year: string } | null = null,
): UseQueryResult<UpcomingIssue[]> {
  const params = new URLSearchParams();
  if (includeDownloaded) params.set("include_downloaded_issues", "true");
  if (week) {
    params.set("week", week.week);
    params.set("year", week.year);
  }
  const query = params.toString();
  return useQuery({
    queryKey: [
      "upcoming",
      includeDownloaded,
      week?.year ?? "current",
      week?.week ?? "current",
    ],
    queryFn: () =>
      apiRequest<UpcomingIssue[]>(
        "GET",
        `/api/upcoming${query ? `?${query}` : ""}`,
      ),
    staleTime: 2 * 60 * 1000, // 2 minutes (more frequent than series)
  });
}

export function useWanted(
  limit = 50,
  offset = 0,
  q = "",
  options: { comicId?: string; enabled?: boolean } = {},
): UseQueryResult<WantedResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  const search = q.trim();
  if (search) params.set("q", search);
  if (options.comicId) params.set("comic_id", options.comicId);
  return useQuery({
    queryKey: ["wanted", limit, offset, search, options.comicId ?? null],
    queryFn: () =>
      apiRequest<WantedResponse>("GET", `/api/wanted?${params.toString()}`),
    staleTime: 2 * 60 * 1000,
    enabled: options.enabled ?? true,
  });
}

export interface WantedSeriesParams {
  limit: number;
  offset: number;
  q: string;
  state: "all" | WantedBucket;
  kind: "all" | "comic" | "manga";
  sort: "problems" | "missing" | "name";
}

/** Wanted folded by series (v2 Wanted page's default view). */
export function useWantedSeries(
  params: WantedSeriesParams,
  enabled = true,
): UseQueryResult<WantedSeriesResponse> {
  const search = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
    state: params.state,
    kind: params.kind,
    sort: params.sort,
  });
  const q = params.q.trim();
  if (q) search.set("q", q);
  return useQuery({
    // Shares the "wanted" prefix so search and skip invalidate it too.
    queryKey: ["wanted", "series", { ...params, q }],
    queryFn: () =>
      apiRequest<WantedSeriesResponse>(
        "GET",
        `/api/wanted/series?${search.toString()}`,
      ),
    staleTime: 2 * 60 * 1000,
    enabled,
  });
}

export function useForceSearch(): UseMutationResult<
  ForceSearchResult,
  Error,
  void
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<ForceSearchResult>("POST", "/api/search/force"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wanted"] });
      queryClient.invalidateQueries({ queryKey: ["upcoming"] });
    },
  });
}

export function useSearchWantedIssue(): UseMutationResult<
  SearchMissingResult,
  Error,
  string
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (issueId) => {
      const preview = await apiRequest<WantedSearchPreview>(
        "GET",
        `/api/series/issues/${issueId}/search-preview`,
      );
      return apiRequest<SearchMissingResult>(
        "POST",
        `/api/series/issues/${issueId}/search`,
        {
          preview_token: preview.preview_token,
          fingerprint: preview.fingerprint,
        },
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wanted"] });
      queryClient.invalidateQueries({ queryKey: ["upcoming"] });
    },
  });
}

export function useBulkQueueIssues(): UseMutationResult<
  BulkIssueResult,
  Error,
  string[]
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (issueIds: string[]) =>
      applySequentially(issueIds, (id) =>
        apiRequest("PUT", `/api/series/issues/${id}/queue`),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wanted"] });
      queryClient.invalidateQueries({ queryKey: ["upcoming"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard", "upcoming"] });
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });
}

export function useBulkUnqueueIssues(): UseMutationResult<
  BulkIssueResult,
  Error,
  string[]
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (issueIds: string[]) =>
      applySequentially(issueIds, (id) =>
        apiRequest("PUT", `/api/series/issues/${id}/unqueue`),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wanted"] });
      queryClient.invalidateQueries({ queryKey: ["upcoming"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard", "upcoming"] });
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });
}
