import {
  useQuery,
  useMutation,
  useQueryClient,
  type UseQueryResult,
  type UseMutationResult,
} from "@tanstack/react-query";
import { apiCall } from "@/lib/api";

/** Preview/validation response from previewMigration API */
interface PreviewMigrationResponse {
  valid: boolean;
  version: string;
  series_count: number;
  issue_count: number;
  tables: MigrationTableSummary[];
  config_categories: string[];
  path_warnings: string[];
  error?: string;
}

interface MigrationTableSummary {
  name: string;
  row_count: number;
}

/** Progress response from getMigrationProgress API */
interface MigrationProgressResponse {
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
      apiCall<PreviewMigrationResponse>("previewMigration", { path }),
  });
}

/** Starts a migration in a background thread. Invalidates series cache on success. */
export function useStartMigration(): UseMutationResult<
  { status: string },
  Error,
  string
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (path: string) =>
      apiCall<{ status: string }>("startMigration", {
        path,
        confirm: "true",
      }),
    onSuccess: () => {
      // Invalidate series data so library refreshes after migration
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["series"] });
      }, 2000);
    },
  });
}

/** Polls migration progress. Stops polling when status is complete or error. */
export function useMigrationProgress(
  enabled = true,
): UseQueryResult<MigrationProgressResponse> {
  return useQuery({
    queryKey: ["migrationProgress"],
    queryFn: () => apiCall<MigrationProgressResponse>("getMigrationProgress"),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "complete" || status === "error" ? false : 1000;
    },
    staleTime: 0,
    gcTime: 30 * 1000,
    enabled,
  });
}
