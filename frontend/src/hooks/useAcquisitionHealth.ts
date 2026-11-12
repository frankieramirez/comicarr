// Copyright (C) 2025–2026 Comicarr contributors

/** Durable, session-authenticated acquisition-health and repair queries. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";

const HEALTH_POLL_MS = 15_000;
const REPAIR_POLL_MS = 2_000;

const TERMINAL_REPAIR_STATES = new Set([
  "completed",
  "failed",
  "conflict",
  "needs_review",
  "rolled_back",
  "rollback_needs_review",
]);

const SENSITIVE_MESSAGE_VALUE =
  /\b(api[_ -]?key|authorization|cookie|credential|password|passkey|secret|token)\s*[=:]\s*[^\s,;]+/gi;
const SENSITIVE_QUERY_VALUE =
  /([?&](?:api[_-]?key|authorization|cookie|credential|password|passkey|secret|token)=)[^&#\s]+/gi;
const AUTHORITY_URL = /(https?:\/\/)[^/@\s]+@/gi;
const MAX_OPERATOR_MESSAGE_LENGTH = 500;

export interface AcquisitionRouteHealth {
  configured?: boolean;
  enabled?: boolean;
  active?: boolean;
  running?: boolean;
  blocked?: boolean;
  blocked_until?: number | string | null;
  blocked_provider_count?: number;
  downstream?: string | null;
  client_ready?: boolean;
  path_ready?: boolean;
  downstream_ready?: boolean;
  restart_safe?: boolean;
  ready?: boolean;
  reason?: string | null;
  last_attempt?: number | string | null;
  last_success?: number | string | null;
  last_failure?: number | string | null;
  last_error?: string | null;
  configured_provider_count?: number;
  executable_provider_count?: number;
  attempted_provider_count?: number;
  providers?: Array<{
    name: string;
    kind: string;
    blocked: boolean;
    attempted: boolean;
    last_attempt: number | string | null;
  }>;
}

export interface AcquisitionWorkerHealth {
  state?: string | null;
  alive?: boolean;
  live?: boolean;
  healthy?: boolean;
  last_heartbeat?: number | string | null;
  last_success?: number | string | null;
  last_failure?: number | string | null;
  last_error?: string | null;
}

export interface AcquisitionRunHealth {
  run_id?: string;
  trigger?: string;
  dispatch?: { state?: string | null };
  completion?: { state?: string | null; completed_at?: string | null };
  accepted?: number;
  processed?: number;
  matched?: number;
  no_match?: number;
  deferred?: number;
  failed?: number;
  oldest_backlog?: number | string | null;
  updated_at?: string | null;
  reason?: string | null;
  error?: string | null;
}

export interface AcquisitionMaintenanceHealth {
  blocked?: boolean;
  reason?: string | null;
  owner?: string | null;
  run_id?: string | null;
  epoch?: number | null;
  heartbeat_at?: string | null;
  active_leases?: number | null;
  drained?: boolean;
  error?: string | null;
}

export interface AcquisitionHealthResponse {
  providers?: Array<Record<string, unknown>>;
  routes?: Record<string, AcquisitionRouteHealth>;
  viable_route?: boolean;
  acquisition?: Record<string, AcquisitionRunHealth>;
  workers?: Record<string, AcquisitionWorkerHealth>;
  maintenance?: AcquisitionMaintenanceHealth;
  blocked_producer_count?: number;
}

export interface ScheduledJobHealth {
  id: string;
  name: string;
  next_run_time?: string | null;
  trigger?: string | null;
  status?: string | null;
  state?: string | null;
  dispatch?: {
    state?: string | null;
    last_attempt?: number | string | null;
    last_success?: number | string | null;
    last_failure?: number | string | null;
    last_error?: string | null;
  };
  last_success_timestamp?: number | string | null;
  last_failure_timestamp?: number | string | null;
  last_error?: string | null;
  /** One-line summary of what the last run did ("1 grabbed of 40 searched"). */
  result?: string | null;
}

/** One configured connection and the answer it gave its last check. */
export interface ConnectionCheck {
  key: string;
  label: string;
  kind: "client" | "indexers" | "metadata";
  route: "nzb" | "torrent" | "ddl" | null;
  checked_at: number | null;
  ok: boolean | null;
  result: string | null;
  latency_ms: number | null;
  latency_label: "median" | "local" | null;
  version: string | null;
  active: number | null;
  responding?: number | null;
  count?: number;
}

export interface SystemJobsResponse {
  jobs: ScheduledJobHealth[];
  acquisition?: Record<string, AcquisitionRunHealth>;
}

export interface BuildIdentity {
  id?: string | null;
  commit?: string | null;
  release?: string | null;
  version?: string | null;
  source?: string | null;
  verified?: boolean;
}

export interface SystemDiagnosticsResponse {
  db_empty?: boolean;
  migration_dismissed?: boolean;
  build?: BuildIdentity;
  acquisition?: AcquisitionHealthResponse;
}

export interface AcquisitionRepairItem {
  sequence?: number;
  entity_type: string;
  entity_id: string;
  entity_key: string;
  series_id?: string;
  intent?: string | null;
  fulfillment?: string | null;
  reason?: string | null;
  date_source?: string | null;
  selected_date?: string | null;
  optional?: boolean;
  selected?: boolean;
}

export interface AcquisitionRepairSummary {
  total?: number;
  owned?: number;
  archived?: number;
  in_flight?: number;
  failed?: number;
  optional_wanted?: number;
  future?: number;
  unknown?: number;
  selected?: number;
}

export interface AcquisitionRepairPreview {
  run_id: string;
  preview_token: string;
  fingerprint: string;
  summary: AcquisitionRepairSummary;
  items: AcquisitionRepairItem[];
}

export interface AcquisitionRepairRun {
  run_id: string;
  scope_type?: string;
  scope_id?: string;
  state: string;
  item_count?: number;
  selected_count?: number;
  applied_count?: number;
  conflict_count?: number;
  rollback_count?: number;
  rollback_conflict_count?: number;
  last_sequence?: number;
  created_at?: string | null;
  confirmed_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface AcquisitionRepairRunResponse {
  success?: boolean;
  run: AcquisitionRepairRun;
  items: AcquisitionRepairItem[];
}

export interface AcquisitionRepairResult {
  success?: boolean;
  run_id: string;
  state: string;
  manifest_id?: string;
  fingerprint?: string;
  item_count?: number;
  selected_count?: number;
  applied_count?: number;
  conflict_count?: number;
  rollback_count?: number;
  rollback_conflict_count?: number;
  last_sequence?: number;
  new_mutations?: number;
}

export interface ConfirmRepairInput {
  runId: string;
  previewToken: string;
  fingerprint: string;
  selectedOptionalKeys: string[];
}

export interface RollbackRepairInput {
  runId: string;
  reason: string;
}

export interface ReconciliationReadyResult {
  success?: boolean;
  reconciliation?: Record<string, unknown>;
  gate?: Record<string, unknown>;
  runtime?: {
    replayed?: { search?: number; refresh?: number };
    queues_started?: string[];
    scheduler_jobs_resumed?: string[];
  };
}

/**
 * Defense in depth for values that are already sanitized by the API. Never
 * render credentials from a partial proxy error or an older server response.
 */
export function sanitizeAcquisitionMessage(value: unknown): string {
  const message = String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
  if (!message) return "—";
  return message
    .replace(SENSITIVE_MESSAGE_VALUE, (match) => {
      const separator = match.includes(":") && !match.includes("=") ? ":" : "=";
      const key = match.slice(0, match.indexOf(separator)).trim();
      return `${key}${separator}[redacted]`;
    })
    .replace(SENSITIVE_QUERY_VALUE, "$1[redacted]")
    .replace(AUTHORITY_URL, "$1[redacted]@")
    .slice(0, MAX_OPERATOR_MESSAGE_LENGTH);
}

/**
 * The acquisition-health read on its own, for callers that need the health
 * projection and nothing else — the dashboard health band reads only
 * `/api/search/health` (docs/architecture/dashboard-spec.md §3.1) and has no use
 * for the scheduler and diagnostics reads `useAcquisitionHealth` also polls.
 *
 * Same query key, so the two share one cache entry and can never disagree.
 */
export function useSearchHealth() {
  return useQuery<AcquisitionHealthResponse>({
    queryKey: ["acquisition", "health"],
    queryFn: () =>
      apiRequest<AcquisitionHealthResponse>("GET", "/api/search/health"),
    staleTime: 5_000,
    refetchInterval: HEALTH_POLL_MS,
  });
}

/**
 * Load the independent health projections and expose session-cookie-backed
 * repair operations. A repair is only polled after the operator has applied
 * or rolled it back; preview remains read-only and token-bound.
 */
export function useAcquisitionHealth(
  repairRunId?: string | null,
  pollRepair = false,
  enabled = true,
) {
  const queryClient = useQueryClient();
  const health = useQuery<AcquisitionHealthResponse>({
    queryKey: ["acquisition", "health"],
    queryFn: () =>
      apiRequest<AcquisitionHealthResponse>("GET", "/api/search/health"),
    enabled,
    staleTime: 5_000,
    refetchInterval: enabled ? HEALTH_POLL_MS : false,
  });
  const jobs = useQuery<SystemJobsResponse>({
    queryKey: ["system", "jobs"],
    queryFn: () =>
      apiRequest<SystemJobsResponse>(
        "GET",
        "/api/system/jobs?include_acquisition=false",
      ),
    enabled,
    staleTime: 5_000,
    refetchInterval: enabled ? HEALTH_POLL_MS : false,
  });
  const diagnostics = useQuery<SystemDiagnosticsResponse>({
    queryKey: ["system", "diagnostics"],
    queryFn: () =>
      apiRequest<SystemDiagnosticsResponse>(
        "GET",
        "/api/system/diagnostics?include_acquisition=false",
      ),
    enabled,
    staleTime: 15_000,
    refetchInterval: enabled ? HEALTH_POLL_MS : false,
  });
  const repairRun = useQuery<AcquisitionRepairRunResponse>({
    queryKey: ["acquisition", "repair", repairRunId],
    queryFn: () =>
      apiRequest<AcquisitionRepairRunResponse>(
        "GET",
        `/api/system/acquisition/repair/${repairRunId}?include_items=false`,
      ),
    enabled: Boolean(enabled && pollRepair && repairRunId),
    staleTime: 0,
    refetchInterval: (query) => {
      const state = query.state.data?.run.state;
      return state && TERMINAL_REPAIR_STATES.has(state)
        ? false
        : REPAIR_POLL_MS;
    },
  });

  const invalidateOperationalState = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["acquisition", "health"] }),
      queryClient.invalidateQueries({ queryKey: ["system", "jobs"] }),
      queryClient.invalidateQueries({ queryKey: ["system", "diagnostics"] }),
    ]);
  };

  const previewRepair = useMutation({
    mutationFn: (seriesId: string) =>
      apiRequest<AcquisitionRepairPreview>(
        "POST",
        "/api/system/acquisition/repair/preview",
        { series_id: seriesId },
      ),
  });
  const confirmRepair = useMutation({
    mutationFn: ({
      runId,
      previewToken,
      fingerprint,
      selectedOptionalKeys,
    }: ConfirmRepairInput) =>
      apiRequest<AcquisitionRepairResult>(
        "POST",
        `/api/system/acquisition/repair/${runId}/confirm`,
        {
          preview_token: previewToken,
          fingerprint,
          selected_optional_keys: selectedOptionalKeys,
        },
      ),
    onSuccess: invalidateOperationalState,
  });
  const applyRepair = useMutation({
    mutationFn: (runId: string) =>
      apiRequest<AcquisitionRepairResult>(
        "POST",
        `/api/system/acquisition/repair/${runId}/apply`,
        {},
      ),
    onSuccess: invalidateOperationalState,
  });
  const rollbackRepair = useMutation({
    mutationFn: ({ runId, reason }: RollbackRepairInput) =>
      apiRequest<AcquisitionRepairResult>(
        "POST",
        `/api/system/acquisition/repair/${runId}/rollback`,
        { reason },
      ),
    onSuccess: invalidateOperationalState,
  });
  const markReconciliationReady = useMutation({
    mutationFn: (reason: string) =>
      apiRequest<ReconciliationReadyResult>(
        "POST",
        "/api/system/acquisition/reconciliation/ready",
        { reason },
      ),
    onSuccess: invalidateOperationalState,
  });

  const refresh = async () => {
    await Promise.all([
      health.refetch(),
      jobs.refetch(),
      diagnostics.refetch(),
    ]);
    if (repairRunId && pollRepair) await repairRun.refetch();
  };

  return {
    health,
    jobs,
    diagnostics,
    repairRun,
    previewRepair,
    confirmRepair,
    applyRepair,
    rollbackRepair,
    markReconciliationReady,
    refresh,
  };
}

/** Scheduled jobs for Activity > Health, sharing Settings' cache entry. */
export function useJobsHealth() {
  return useQuery<SystemJobsResponse>({
    queryKey: ["system", "jobs"],
    queryFn: () =>
      apiRequest<SystemJobsResponse>(
        "GET",
        "/api/system/jobs?include_acquisition=false",
      ),
    staleTime: 5_000,
    refetchInterval: HEALTH_POLL_MS,
  });
}

export interface RunJobResult {
  accepted: boolean;
  state: string;
  error?: string;
  next_run_time?: string;
}

/** Start one scheduled job now (POST /api/system/jobs/{id}/run). */
export function useRunJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) =>
      apiRequest<RunJobResult>(
        "POST",
        `/api/system/jobs/${encodeURIComponent(jobId)}/run`,
      ),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["system", "jobs"] });
    },
  });
}

const CONNECTIONS_KEY = ["system", "connections"] as const;

/** Every configured connection with its last check (Activity > Health, Settings). */
export function useConnections() {
  return useQuery<{ connections: ConnectionCheck[] }>({
    queryKey: CONNECTIONS_KEY,
    queryFn: () =>
      apiRequest<{ connections: ConnectionCheck[] }>(
        "GET",
        "/api/system/connections",
      ),
    staleTime: 10_000,
    refetchInterval: HEALTH_POLL_MS * 2,
  });
}

/** Check one connection now ("indexers" checks every indexer), or all of them. */
export function useTestConnection() {
  const queryClient = useQueryClient();
  return useMutation<
    ConnectionCheck | { connections: ConnectionCheck[] },
    Error,
    string | null
  >({
    mutationFn: (key: string | null) =>
      key
        ? apiRequest<ConnectionCheck>(
            "POST",
            `/api/system/connections/${encodeURIComponent(key)}/test`,
          )
        : apiRequest<{ connections: ConnectionCheck[] }>(
            "POST",
            "/api/system/connections/test",
          ),
    onSuccess: (data) => {
      queryClient.setQueryData<{ connections: ConnectionCheck[] }>(
        CONNECTIONS_KEY,
        (current) => {
          const fresh: ConnectionCheck[] =
            "connections" in data ? data.connections : [data];
          const rows = current?.connections ?? [];
          const merged = rows.map(
            (row) => fresh.find((next) => next.key === row.key) ?? row,
          );
          for (const next of fresh)
            if (!merged.some((row) => row.key === next.key)) merged.push(next);
          return { connections: merged };
        },
      );
    },
  });
}
