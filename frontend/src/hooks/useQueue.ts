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
  verb: "queued" | "skipped",
  failureVerb: "queue" | "skip",
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
): UseQueryResult<UpcomingIssue[]> {
  return useQuery({
    queryKey: ["upcoming", includeDownloaded],
    queryFn: () =>
      apiRequest<UpcomingIssue[]>(
        "GET",
        `/api/upcoming${includeDownloaded ? "?include_downloaded_issues=true" : ""}`,
      ),
    staleTime: 2 * 60 * 1000, // 2 minutes (more frequent than series)
  });
}

export function useWanted(
  limit = 50,
  offset = 0,
  q = "",
): UseQueryResult<WantedResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  const search = q.trim();
  if (search) params.set("q", search);
  return useQuery({
    queryKey: ["wanted", limit, offset, search],
    queryFn: () =>
      apiRequest<WantedResponse>("GET", `/api/wanted?${params.toString()}`),
    staleTime: 2 * 60 * 1000,
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
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });
}
