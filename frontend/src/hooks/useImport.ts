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
  ImportBucket,
  ImportGroup,
  ImportPendingSummary,
  ImportPickPanel,
  ImportRemoteCandidates,
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
  bucket: ImportBucket = "needs_pick",
  search = "",
): UseQueryResult<ImportPendingResponse> {
  const q = search.trim();
  return useQuery({
    queryKey: ["importPending", limit, offset, bucket, q],
    queryFn: () =>
      apiRequest<ImportPendingResponse>(
        "GET",
        `/api/import?limit=${limit}&offset=${offset}&bucket=${bucket}${
          q ? `&q=${encodeURIComponent(q)}` : ""
        }`,
      ),
    staleTime: 30 * 1000, // 30 seconds - imports may change frequently
  });
}

/** The pick panel for one review group, keyed by its files. */
export function useImportCandidates(
  impIds: string[],
): UseQueryResult<ImportPickPanel> {
  return useQuery({
    queryKey: ["importCandidates", impIds],
    queryFn: () =>
      apiRequest<ImportPickPanel>("POST", "/api/import/candidates", {
        imp_ids: impIds,
      }),
    enabled: impIds.length > 0,
    staleTime: 30 * 1000,
  });
}

/** Series not in the library yet; costs a provider search, so it is cached long. */
export function useImportRemoteCandidates(
  impIds: string[],
  contentType: "comic" | "manga",
  enabled = true,
): UseQueryResult<ImportRemoteCandidates> {
  return useQuery({
    queryKey: ["importRemoteCandidates", impIds, contentType],
    queryFn: () =>
      apiRequest<ImportRemoteCandidates>(
        "POST",
        "/api/import/candidates/remote",
        {
          imp_ids: impIds,
          content_type: contentType === "manga" ? "manga" : undefined,
        },
      ),
    enabled: enabled && impIds.length > 0,
    staleTime: 10 * 60 * 1000,
    retry: false,
  });
}

interface ImportConfidentResponse {
  groups: number;
  imported: number;
  failed: Array<{ name: string; error: string }>;
}

export function useImportConfident(): UseMutationResult<
  ImportConfidentResponse,
  Error,
  void
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<ImportConfidentResponse>("POST", "/api/import/confident"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["importPending"] });
      queryClient.invalidateQueries({ queryKey: ["importCandidates"] });
    },
  });
}

export function useMatchImport(): UseMutationResult<
  MatchImportResponse,
  Error,
  {
    impIds: string[];
    comicId: string;
    comicName?: string;
    issueId?: string;
    addMissing?: boolean;
  }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ impIds, comicId, comicName, issueId, addMissing = false }) =>
      apiRequest<MatchImportResponse>("POST", "/api/import/match", {
        imp_ids: impIds,
        comic_id: comicId,
        comic_name: comicName,
        issue_id: issueId,
        add_missing: addMissing,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["importPending"] });
      queryClient.invalidateQueries({ queryKey: ["importCandidates"] });
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
      queryClient.invalidateQueries({ queryKey: ["importCandidates"] });
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
      queryClient.invalidateQueries({ queryKey: ["importCandidates"] });
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
      queryClient.invalidateQueries({ queryKey: ["importCandidates"] });
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
