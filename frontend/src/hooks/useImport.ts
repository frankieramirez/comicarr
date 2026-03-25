import {
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryResult,
  type UseMutationResult,
} from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
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
  success: boolean;
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
      apiRequest<ImportPendingResponse>(
        "GET",
        `/api/import?limit=${limit}&offset=${offset}&include_ignored=${includeIgnored}`,
      ),
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
      apiRequest<MatchImportResponse>("POST", "/api/import/match", {
        imp_ids: impIds,
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
      apiRequest<IgnoreImportResponse>("POST", "/api/import/ignore", {
        imp_ids: impIds,
        ignore,
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
      apiRequest<DeleteImportResponse>("DELETE", "/api/import", {
        imp_ids: impIds,
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
    mutationFn: () =>
      apiRequest<RefreshImportResponse>("POST", "/api/import/refresh"),
    onSuccess: () => {
      // Delay invalidation to give scan time to start
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["importPending"] });
      }, 2000);
    },
  });
}
