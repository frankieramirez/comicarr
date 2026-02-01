import {
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryResult,
  type UseMutationResult,
} from "@tanstack/react-query";
import { apiCall } from "@/lib/api";
import type { ImportGroup, PaginationMeta } from "@/types";

interface ImportPendingResponse {
  imports: ImportGroup[];
  pagination: PaginationMeta;
}

interface MatchImportResponse {
  matched: number;
  comic_id: string;
  comic_name: string;
}

interface IgnoreImportResponse {
  updated: number;
  ignored: boolean;
}

interface DeleteImportResponse {
  deleted: number;
}

interface RefreshImportResponse {
  message: string;
}

// Query Hooks
export function useImportPending(
  limit = 50,
  offset = 0,
  includeIgnored = false,
): UseQueryResult<ImportPendingResponse> {
  return useQuery({
    queryKey: ["importPending", limit, offset, includeIgnored],
    queryFn: () =>
      apiCall<ImportPendingResponse>("getImportPending", {
        limit,
        offset,
        include_ignored: includeIgnored ? "true" : "false",
      }),
    staleTime: 30 * 1000, // 30 seconds - imports may change frequently
  });
}

// Mutation Hooks
export function useMatchImport(): UseMutationResult<
  MatchImportResponse,
  Error,
  { impIds: string[]; comicId: string; issueId?: string }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ impIds, comicId, issueId }) =>
      apiCall<MatchImportResponse>("matchImport", {
        imp_ids: impIds.join(","),
        comic_id: comicId,
        issue_id: issueId,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["importPending"] });
    },
  });
}

export function useIgnoreImport(): UseMutationResult<
  IgnoreImportResponse,
  Error,
  { impIds: string[]; ignore?: boolean }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ impIds, ignore = true }) =>
      apiCall<IgnoreImportResponse>("ignoreImport", {
        imp_ids: impIds.join(","),
        ignore: ignore ? "true" : "false",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["importPending"] });
    },
  });
}

export function useDeleteImport(): UseMutationResult<
  DeleteImportResponse,
  Error,
  string[]
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (impIds: string[]) =>
      apiCall<DeleteImportResponse>("deleteImport", {
        imp_ids: impIds.join(","),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["importPending"] });
    },
  });
}

export function useRefreshImport(): UseMutationResult<
  RefreshImportResponse,
  Error,
  void
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiCall<RefreshImportResponse>("refreshImport"),
    onSuccess: () => {
      // Delay invalidation to give scan time to start
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["importPending"] });
      }, 2000);
    },
  });
}
