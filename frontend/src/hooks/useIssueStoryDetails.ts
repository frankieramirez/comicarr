// Copyright (C) 2025–2026 Comicarr contributors

/** The facts beside an issue's story, and the manual-import path. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import {
  ACTIVITY_BAND_QUERY_KEY,
  ACTIVITY_STATUS_QUERY_KEY,
  ACTIVITY_TIMELINE_QUERY_KEY,
} from "@/lib/activityKeys";

export interface SearchCandidate {
  title: string;
  provider: string;
  source_kind?: string | null;
  size_bytes: number | null;
  pack: boolean;
  status: string;
  reason_code: string | null;
  reason: string | null;
  chosen?: boolean;
}

export interface SearchHistory {
  searched_at: string;
  total: number;
  accepted_count: number;
  rejected_count: number;
  providers: string[];
  accepted: SearchCandidate[];
  rejected: SearchCandidate[];
  reasons: { code: string; label: string; count: number }[];
}

export interface IssueStoryDetails {
  issue_id: string;
  attempts: { search: number; grab: number; download: number; import: number };
  search: SearchHistory | null;
  chosen: string | null;
  log: { query: string; lines: string[] };
}

export function useIssueStoryDetails(issueId: string | undefined) {
  return useQuery<IssueStoryDetails>({
    queryKey: ["issue-story-details", issueId],
    enabled: Boolean(issueId),
    queryFn: () =>
      apiRequest<IssueStoryDetails>(
        "GET",
        `/api/series/issues/${encodeURIComponent(issueId ?? "")}/story`,
      ),
    staleTime: 15_000,
  });
}

export interface ImportSource {
  release_key: string;
  nzb_name: string | null;
  nzb_folder: string | null;
}

export function useImportSource(releaseKey: string | null) {
  return useQuery<ImportSource>({
    queryKey: ["attention", "import-source", releaseKey],
    enabled: Boolean(releaseKey),
    queryFn: () =>
      apiRequest<ImportSource>(
        "GET",
        `/api/attention/import-source?release_key=${encodeURIComponent(releaseKey ?? "")}`,
      ),
    retry: false,
  });
}

interface ResolveResult {
  success: boolean;
  error?: string;
  results?: { ok: boolean; error: string | null }[];
}

/** Import one waiting download from the folder the operator names. */
export function useManualImport() {
  const queryClient = useQueryClient();
  return useMutation<ResolveResult, Error, ImportSource>({
    mutationFn: async ({ release_key, nzb_name, nzb_folder }) => {
      const result = await apiRequest<ResolveResult>(
        "POST",
        "/api/attention/resolve",
        {
          action: "import",
          release_keys: [release_key],
          import_source: { nzb_name, nzb_folder },
        },
      );
      if (!result.success)
        throw new Error(
          result.results?.[0]?.error || result.error || "Import didn't start.",
        );
      return result;
    },
    onSuccess: () => {
      for (const queryKey of [
        ACTIVITY_BAND_QUERY_KEY,
        ACTIVITY_TIMELINE_QUERY_KEY,
        ACTIVITY_STATUS_QUERY_KEY,
      ])
        void queryClient.invalidateQueries({ queryKey });
      void queryClient.invalidateQueries({
        queryKey: ["issue-story-details"],
      });
    },
  });
}

/** "21 wrong issue · 9 wrong series · 2 too small" for the last search. */
export function rejectionBreakdown(search: SearchHistory | null | undefined) {
  if (!search || search.reasons.length === 0) return "";
  return search.reasons
    .slice(0, 4)
    .map((reason) => `${reason.count} ${reason.label}`)
    .join(" · ");
}
