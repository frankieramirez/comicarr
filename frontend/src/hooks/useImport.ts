import {
  type QueryClient,
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryResult,
  type UseMutationResult,
} from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import type {
  ImportGroup,
  ImportPendingSummary,
  PaginationMeta,
  ScanProgress,
} from "@/types";

interface ImportPendingResponse {
  imports: ImportGroup[];
  pagination: PaginationMeta;
  summary?: ImportPendingSummary;
}

interface MatchImportResponse {
  success: boolean;
  matched: number;
  imported: number;
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

interface UpdateImportMetadataResponse {
  success: boolean;
  imp_id: string;
  issue_number: string;
}

interface RefreshImportResponse {
  success: boolean;
  message: string;
}

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

export function useMatchImport(): UseMutationResult<
  MatchImportResponse,
  Error,
  { impIds: string[]; comicId: string; comicName?: string; issueId?: string }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ impIds, comicId, comicName, issueId }) =>
      apiRequest<MatchImportResponse>("POST", "/api/import/match", {
        imp_ids: impIds,
        comic_id: comicId,
        comic_name: comicName,
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

export function useUpdateImportMetadata(): UseMutationResult<
  UpdateImportMetadataResponse,
  Error,
  { impId: string; issueNumber: string }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ impId, issueNumber }) =>
      apiRequest<UpdateImportMetadataResponse>(
        "PATCH",
        `/api/import/${impId}`,
        {
          issue_number: issueNumber,
        },
      ),
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
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["importPending"] });
      }, 2000);
    },
  });
}

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
    onMutate: () => {
      queryClient.removeQueries({ queryKey: ["mangaScanProgress"] });
    },
    mutationFn: () =>
      apiRequest<MangaScanResponse>("POST", "/api/import/manga/scan"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mangaScanProgress"] });
    },
  });
}

function refetchWhileScanning(query: {
  state: { data?: { status?: string | null } };
}) {
  return query.state.data?.status === "scanning" ? 2000 : false;
}

function clearImportedScanResults(
  queryClient: QueryClient,
  queryKey: readonly ["comicScanProgress" | "mangaScanProgress"],
) {
  queryClient.setQueryData<ScanProgress>(queryKey, (current) =>
    current ? { ...current, results: null, scan_id: null } : current,
  );
  queryClient.invalidateQueries({ queryKey });
  queryClient.invalidateQueries({ queryKey: ["series"] });
}

export function useMangaScanProgress(): UseQueryResult<MangaScanProgress> {
  return useQuery({
    queryKey: ["mangaScanProgress"],
    queryFn: () =>
      apiRequest<MangaScanProgress>("GET", "/api/import/manga/progress"),
    refetchInterval: refetchWhileScanning,
  });
}

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
      clearImportedScanResults(queryClient, ["mangaScanProgress"]);
    },
  });
}

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
    onMutate: () => {
      queryClient.removeQueries({ queryKey: ["comicScanProgress"] });
    },
    mutationFn: () =>
      apiRequest<ComicScanResponse>("POST", "/api/import/comic/scan"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["comicScanProgress"] });
    },
  });
}

export function useComicScanProgress(): UseQueryResult<ScanProgress> {
  return useQuery({
    queryKey: ["comicScanProgress"],
    queryFn: () =>
      apiRequest<ScanProgress>("GET", "/api/import/comic/progress"),
    refetchInterval: refetchWhileScanning,
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
      clearImportedScanResults(queryClient, ["comicScanProgress"]);
    },
  });
}
