import {
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryResult,
  type UseMutationResult,
} from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import type { ImportGroup, PaginationMeta, ScanProgress } from "@/types";

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

// Manga scan hooks

interface MangaScanResponse {
  success: boolean;
  message: string;
}

type MangaScanProgress = ScanProgress;

export function useMangaScan(): UseMutationResult<
  MangaScanResponse,
  Error,
  void
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<MangaScanResponse>("POST", "/api/import/manga/scan"),
    onSuccess: () => {
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["mangaScanProgress"] });
        queryClient.invalidateQueries({ queryKey: ["series"] });
      }, 2000);
    },
  });
}

export function useMangaScanProgress(
  enabled = false,
): UseQueryResult<MangaScanProgress> {
  return useQuery({
    queryKey: ["mangaScanProgress"],
    queryFn: () =>
      apiRequest<MangaScanProgress>("GET", "/api/import/manga/progress"),
    enabled,
    refetchInterval: enabled ? 2000 : false,
  });
}

// Manga scan confirm hook
interface ScanConfirmResponse {
  success: boolean;
  imported: number;
  errors: { comicid: string; error: string }[];
}

export function useMangaScanConfirm(): UseMutationResult<
  ScanConfirmResponse,
  Error,
  { scanId: string; selectedIds: string[] }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ scanId, selectedIds }) =>
      apiRequest<ScanConfirmResponse>("POST", "/api/import/manga/confirm", {
        scan_id: scanId,
        selected_ids: selectedIds,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mangaScanProgress"] });
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });
}

// Comic scan hooks

interface ComicScanResponse {
  success: boolean;
  message: string;
}

export function useComicScan(): UseMutationResult<
  ComicScanResponse,
  Error,
  void
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<ComicScanResponse>("POST", "/api/import/comic/scan"),
    onSuccess: () => {
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["comicScanProgress"] });
        queryClient.invalidateQueries({ queryKey: ["series"] });
      }, 2000);
    },
  });
}

export function useComicScanProgress(
  enabled = false,
): UseQueryResult<ScanProgress> {
  return useQuery({
    queryKey: ["comicScanProgress"],
    queryFn: () =>
      apiRequest<ScanProgress>("GET", "/api/import/comic/progress"),
    enabled,
    refetchInterval: enabled ? 2000 : false,
  });
}

export function useComicScanConfirm(): UseMutationResult<
  ScanConfirmResponse,
  Error,
  { scanId: string; selectedIds: string[] }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ scanId, selectedIds }) =>
      apiRequest<ScanConfirmResponse>("POST", "/api/import/comic/confirm", {
        scan_id: scanId,
        selected_ids: selectedIds,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["comicScanProgress"] });
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });
}
