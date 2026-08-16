import {
  useQuery,
  useMutation,
  useQueryClient,
  type QueryClient,
  type UseQueryResult,
  type UseMutationResult,
} from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import type {
  Comic,
  ContentType,
  SearchMissingConfirmationInput,
  SearchMissingPreview,
  SearchMissingResult,
  SearchRunCompletionState,
  SearchRunResult,
  SearchRunRetryResult,
  SeriesDetail,
} from "@/types";

const SEARCH_RUN_POLL_MS = 2_000;
const TERMINAL_SEARCH_RUN_STATES = new Set<SearchRunCompletionState>([
  "completed",
  "partial",
  "blocked",
  "failed",
]);

function invalidateSeriesAcquisitionQueries(
  queryClient: QueryClient,
  comicId: string,
) {
  queryClient.invalidateQueries({ queryKey: ["series"] });
  queryClient.invalidateQueries({ queryKey: ["series", comicId] });
  queryClient.invalidateQueries({ queryKey: ["wanted"] });
}

/**
 * Fetch all series from the library
 */
export function useSeries(): UseQueryResult<Comic[]> {
  return useQuery({
    queryKey: ["series"],
    queryFn: () => apiRequest<Comic[]>("GET", "/api/series"),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Fetch a single series with its issues
 */
export function useSeriesDetail(
  comicId: string | undefined,
): UseQueryResult<SeriesDetail> {
  return useQuery({
    queryKey: ["series", comicId],
    queryFn: () => apiRequest<SeriesDetail>("GET", `/api/series/${comicId}`),
    enabled: !!comicId,
  });
}

/**
 * Prepare a one-shot, session-bound preview. It is disabled until the UI opens
 * the confirmation flow, so viewing a series never mints disposable tokens.
 */
export function useSearchMissingPreview(
  comicId: string | undefined,
): UseQueryResult<SearchMissingPreview> {
  return useQuery({
    queryKey: ["series", comicId, "search-missing-preview"],
    queryFn: () =>
      apiRequest<SearchMissingPreview>(
        "GET",
        `/api/series/${comicId}/search-missing/preview`,
      ),
    enabled: false,
    staleTime: Infinity,
  });
}

/** Confirm a preview exactly once and let the durable run own subsequent work. */
export function useConfirmSearchMissing(): UseMutationResult<
  SearchMissingResult,
  Error,
  SearchMissingConfirmationInput
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ comicId, previewToken, fingerprint }) =>
      apiRequest<SearchMissingResult>(
        "POST",
        `/api/series/${comicId}/search-missing`,
        {
          confirm: true,
          preview_token: previewToken,
          fingerprint,
        },
      ),
    onSuccess: (_, { comicId }) => {
      invalidateSeriesAcquisitionQueries(queryClient, comicId);
    },
  });
}

/** Poll a durable series search until the server reports a terminal outcome. */
export function useSearchRun(
  runId: string | null | undefined,
): UseQueryResult<SearchRunResult> {
  return useQuery({
    queryKey: ["search-run", runId],
    queryFn: () =>
      apiRequest<SearchRunResult>("GET", `/api/search/runs/${runId}`),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const completionState = query.state.data?.run.completion_state;
      return completionState && TERMINAL_SEARCH_RUN_STATES.has(completionState)
        ? false
        : SEARCH_RUN_POLL_MS;
    },
  });
}

/** Retry only durable search items that missed their queue handoff. */
export function useRetrySearchRun(): UseMutationResult<
  SearchRunRetryResult,
  Error,
  string
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (runId: string) =>
      apiRequest<SearchRunRetryResult>(
        "POST",
        `/api/search/runs/${runId}/retry`,
      ),
    onSuccess: (_, runId) => {
      queryClient.invalidateQueries({ queryKey: ["search-run", runId] });
      queryClient.invalidateQueries({ queryKey: ["series"] });
      queryClient.invalidateQueries({ queryKey: ["wanted"] });
    },
  });
}

/**
 * Pause a series
 */
export function usePauseSeries(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId: string) =>
      apiRequest("PUT", `/api/series/${comicId}/pause`),
    onSuccess: (_, comicId) => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
      queryClient.invalidateQueries({ queryKey: ["series", comicId] });
    },
  });
}

/**
 * Resume a series
 */
export function useResumeSeries(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId: string) =>
      apiRequest("PUT", `/api/series/${comicId}/resume`),
    onSuccess: (_, comicId) => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
      queryClient.invalidateQueries({ queryKey: ["series", comicId] });
    },
  });
}

export interface SeriesSearchSettingsInput {
  comicId: string;
  allowPacks?: boolean;
  ignoreType?: boolean;
  bareNumberMode?: "auto" | "volumes" | "chapters";
  monitorMode?: "blended" | "volumes" | "chapters";
}

export interface SeriesContentKindInput {
  comicId: string;
  contentType: ContentType;
}

export function useUpdateSeriesContentKind(): UseMutationResult<
  { success: boolean; content_type: ContentType },
  Error,
  SeriesContentKindInput
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ comicId, contentType }) =>
      apiRequest<{ success: boolean; content_type: ContentType }>(
        "PATCH",
        `/api/series/${comicId}/content-kind`,
        { content_type: contentType },
      ),
    onSuccess: (_, { comicId }) => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
      queryClient.invalidateQueries({ queryKey: ["series", comicId] });
    },
  });
}

/**
 * Update per-series search flags (pack matching / booktype override)
 */
export function useUpdateSeriesSearchSettings(): UseMutationResult<
  unknown,
  Error,
  SeriesSearchSettingsInput
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      comicId,
      allowPacks,
      ignoreType,
      bareNumberMode,
      monitorMode,
    }) =>
      apiRequest("PATCH", `/api/series/${comicId}/search-settings`, {
        ...(allowPacks !== undefined && { allow_packs: allowPacks }),
        ...(ignoreType !== undefined && { ignore_type: ignoreType }),
        ...(bareNumberMode !== undefined && {
          bare_number_mode: bareNumberMode,
        }),
        ...(monitorMode !== undefined && { monitor_mode: monitorMode }),
      }),
    onSuccess: (_, { comicId }) => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
      queryClient.invalidateQueries({ queryKey: ["series", comicId] });
    },
  });
}

/**
 * Refresh series metadata
 */
export function useRefreshSeries(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId: string) =>
      apiRequest("POST", `/api/series/${comicId}/refresh`),
    onSuccess: (_, comicId) => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
      queryClient.invalidateQueries({ queryKey: ["series", comicId] });
    },
  });
}

/**
 * Delete a series
 */
export function useDeleteSeries(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (comicId: string) =>
      apiRequest("DELETE", `/api/series/${comicId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });
}

/**
 * Bulk delete multiple series
 */
export function useBulkDeleteSeries(): UseMutationResult<
  unknown,
  Error,
  string[]
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (ids: string[]) =>
      apiRequest("POST", "/api/series/bulk-delete", { ids }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });
}

/**
 * Bulk pause multiple series
 */
export function useBulkPauseSeries(): UseMutationResult<
  unknown,
  Error,
  string[]
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (ids: string[]) =>
      apiRequest("POST", "/api/series/bulk-pause", { ids }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });
}

/**
 * Bulk resume multiple series
 */
export function useBulkResumeSeries(): UseMutationResult<
  unknown,
  Error,
  string[]
> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (ids: string[]) =>
      apiRequest("POST", "/api/series/bulk-resume", { ids }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });
}

/**
 * Queue an issue (mark as wanted)
 */
export function useQueueIssue(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (issueId: string) =>
      apiRequest("PUT", `/api/series/issues/${issueId}/queue`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
      queryClient.invalidateQueries({ queryKey: ["wanted"] });
    },
  });
}

/**
 * Unqueue an issue (mark as skipped)
 */
export function useUnqueueIssue(): UseMutationResult<unknown, Error, string> {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (issueId: string) =>
      apiRequest("PUT", `/api/series/issues/${issueId}/unqueue`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
      queryClient.invalidateQueries({ queryKey: ["wanted"] });
    },
  });
}
