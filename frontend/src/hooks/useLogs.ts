import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";

/**
 * The three levels Settings → Logs has to keep straight.
 *
 * `saved` is what the dial edits (`LOG_LEVEL` in `config.ini`), `effective` is
 * what the process is logging at right now, and `restart_*` is what the startup
 * chain resolves to next boot. `pinned` says a startup argument or
 * `COMICARR_LOG_LEVEL` outranks the config file, which is the case where the
 * dial cannot make its value stick.
 */
export interface LogLevelContext {
  effective: number;
  effective_name: string;
  saved: number;
  saved_name: string;
  restart_level: number;
  restart_name: string;
  restart_source: string;
  pinned: boolean;
}

export interface LogFile {
  selector: string;
  name: string;
  size: number;
  modified: string;
}

export interface LogSearch {
  selector: string;
  query?: string;
  component?: string;
  severity?: string;
}

export interface LogsResponse {
  logs: string[];
  level: LogLevelContext;
  requested?: number;
  path?: string | null;
  error?: string;
  file?: LogFile;
  lines_scanned?: number;
  records_matched?: number;
  records_returned?: number;
  truncated?: boolean;
  record_limit?: number;
  byte_limit?: number;
}

/** Tail line counts for legacy calls, or whole-record limits for searches. */
export const LOG_LINE_CHOICES = [200, 1000, 5000] as const;

export const LOGS_QUERY_KEY = ["system", "logs"] as const;

/**
 * The current-file tail, or whole-record server search when `search` is supplied.
 *
 * No polling and no SSE: `activity` is this app's only narrative channel, and a
 * log surface that refetched on a timer would fight the operator's scroll
 * position while they read. Refresh is a button.
 */
export function useLogs(
  lines: number,
  options?: { enabled?: boolean; search?: LogSearch },
): UseQueryResult<LogsResponse> {
  const enabled = options?.enabled ?? true;
  const params = new URLSearchParams({ lines: String(lines) });
  if (options?.search) {
    for (const [key, value] of Object.entries(options.search)) {
      if (value) params.set(key, value);
    }
  }
  return useQuery({
    queryKey: [...LOGS_QUERY_KEY, params.toString()],
    queryFn: () =>
      apiRequest<LogsResponse>("GET", `/api/system/logs?${params}`),
    enabled,
    staleTime: 0,
    refetchOnWindowFocus: false,
    retry: false,
  });
}

export function useLogFiles() {
  return useQuery({
    queryKey: [...LOGS_QUERY_KEY, "files"],
    queryFn: () =>
      apiRequest<{ files: LogFile[] }>("GET", "/api/system/logs/files"),
    refetchOnWindowFocus: false,
    retry: false,
  });
}

export interface StartNewLogResult {
  success: boolean;
  /** false means logging has no file sink; only the in-memory buffer cleared. */
  rotated: boolean;
  error?: string;
}

/**
 * Start a new log file (#743): the server rolls `comicarr.log` over — the old
 * file survives as a rotated archive — and empties the Web UI buffer. Clearing
 * and rotating are the same action from the viewer's perspective, so this is
 * the only verb the page offers.
 */
export function useStartNewLog(): UseMutationResult<
  StartNewLogResult,
  Error,
  void
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<StartNewLogResult>("POST", "/api/system/logs/rotate"),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: LOGS_QUERY_KEY }),
  });
}
