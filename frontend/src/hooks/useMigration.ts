import {
  useQuery,
  useMutation,
  type UseQueryResult,
  type UseMutationResult,
} from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";

/** Preview/validation response from previewMigration API */
export interface PreviewMigrationResponse {
  valid: boolean;
  version: string;
  series_count: number;
  issue_count: number;
  tables: MigrationTableSummary[];
  config_categories: string[];
  path_warnings: string[];
  error?: string;
}

export interface MigrationTableSummary {
  name: string;
  row_count: number;
}

/** Progress response from getMigrationProgress API */
export interface MigrationProgressResponse {
  status: MigrationStatus;
  current_table: string;
  tables_complete: number;
  tables_total: number;
  error?: string;
}

export type MigrationStatus =
  | "idle"
  | "validating"
  | "migrating"
  | "complete"
  | "error";

/** Validates a Mylar3 source path and returns preview data. */
export function usePreviewMigration(): UseMutationResult<
  PreviewMigrationResponse,
  Error,
  string
> {
  return useMutation({
    mutationFn: (path: string) =>
      apiRequest<PreviewMigrationResponse>(
        "POST",
        "/api/system/migration/preview",
        { path },
      ),
  });
}

/** Starts a migration in a background thread. */
export function useStartMigration(): UseMutationResult<
  { status: string },
  Error,
  string
> {
  return useMutation({
    mutationFn: (path: string) =>
      apiRequest<{ status: string }>("POST", "/api/system/migration/start", {
        path,
      }),
  });
}

/** Polls migration progress. Stops polling when status is complete or error. */
export function useMigrationProgress(
  enabled = true,
): UseQueryResult<MigrationProgressResponse> {
  return useQuery({
    queryKey: ["migrationProgress"],
    queryFn: () =>
      apiRequest<MigrationProgressResponse>(
        "GET",
        "/api/system/migration/progress",
      ),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "complete" || status === "error" ? false : 1000;
    },
    staleTime: 0,
    gcTime: 30 * 1000,
    enabled,
  });
}
