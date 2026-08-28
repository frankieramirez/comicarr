// Copyright (C) 2025–2026 Comicarr contributors

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleAlert,
  CircleX,
  Clock3,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { SettingGroup } from "./SettingGroup";
import {
  sanitizeAcquisitionMessage,
  useAcquisitionHealth,
  type AcquisitionRepairPreview,
  type AcquisitionRepairResult,
  type AcquisitionRepairRun,
  type AcquisitionRouteHealth,
  type AcquisitionRunHealth,
  type AcquisitionWorkerHealth,
  type ScheduledJobHealth,
} from "@/hooks/useAcquisitionHealth";

type Tone = "ready" | "warning" | "danger" | "neutral";

const APPLYABLE_REPAIR_STATES = new Set([
  "confirmed",
  "applying",
  "waiting_for_drain",
  "canary_complete",
]);
const ROLLBACKABLE_REPAIR_STATES = new Set(["completed", "needs_review"]);

function asCount(value: number | undefined | null) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function humanize(value: string | null | undefined, fallback = "unknown") {
  const text = String(value ?? "").trim();
  return text ? text.replace(/[_-]+/g, " ") : fallback;
}

function parseMoment(value: number | string | null | undefined) {
  if (value === null || value === undefined || value === "") return null;
  const numeric = typeof value === "number" ? value : Number(value);
  const date = Number.isFinite(numeric)
    ? new Date(numeric * 1000)
    : new Date(String(value));
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatMoment(value: number | string | null | undefined) {
  const date = parseMoment(value);
  if (!date) return "—";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function formatAge(value: number | string | null | undefined) {
  const date = parseMoment(value);
  if (!date) return "—";
  const elapsedSeconds = Math.round((Date.now() - date.getTime()) / 1000);
  const prefix = elapsedSeconds < 0 ? "in " : "";
  const seconds = Math.abs(elapsedSeconds);
  if (seconds < 60) return `${prefix}${seconds}s`;
  if (seconds < 3_600) return `${prefix}${Math.round(seconds / 60)}m`;
  if (seconds < 86_400) return `${prefix}${Math.round(seconds / 3_600)}h`;
  return `${prefix}${Math.round(seconds / 86_400)}d`;
}

function errorMessage(error: unknown) {
  if (error instanceof Error) return sanitizeAcquisitionMessage(error.message);
  return sanitizeAcquisitionMessage(error);
}

function toneForBoolean(value: boolean | undefined): Tone {
  if (value === true) return "ready";
  if (value === false) return "danger";
  return "neutral";
}

function toneForState(value: string | null | undefined): Tone {
  const state = String(value ?? "").toLowerCase();
  if (
    [
      "ready",
      "completed",
      "succeeded",
      "accepted",
      "idle",
      "waiting",
      "finalized",
    ].includes(state)
  ) {
    return "ready";
  }
  if (
    [
      "failed",
      "error",
      "missed",
      "conflict",
      "needs_review",
      "rollback_needs_review",
    ].includes(state)
  ) {
    return "danger";
  }
  if (
    [
      "partial",
      "queued",
      "running",
      "applying",
      "blocked",
      "waiting_for_drain",
      "paused",
    ].includes(state)
  ) {
    return "warning";
  }
  return "neutral";
}

function StatusPill({
  label,
  tone = "neutral",
}: {
  label: string;
  tone?: Tone;
}) {
  const palette: Record<
    Tone,
    { border: string; color: string; background: string }
  > = {
    ready: {
      border: "color-mix(in oklab, var(--status-success) 36%, transparent)",
      color: "var(--status-success)",
      background: "color-mix(in oklab, var(--status-success) 11%, transparent)",
    },
    warning: {
      border: "color-mix(in oklab, var(--status-warning) 42%, transparent)",
      color: "var(--status-warning)",
      background: "color-mix(in oklab, var(--status-warning) 10%, transparent)",
    },
    danger: {
      border: "color-mix(in oklab, var(--status-error) 42%, transparent)",
      color: "var(--status-error)",
      background: "var(--status-error-bg)",
    },
    neutral: {
      border: "var(--border)",
      color: "var(--muted-foreground)",
      background: "var(--secondary)",
    },
  };
  const style = palette[tone];

  return (
    <span
      className="inline-flex max-w-full items-center rounded-full border px-2 py-0.5 font-mono text-[10px] tracking-[0.04em]"
      style={style}
    >
      <span className="truncate">{label}</span>
    </span>
  );
}

function Metric({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string | number;
  tone?: Tone;
}) {
  const color =
    tone === "ready"
      ? "var(--status-success)"
      : tone === "warning"
        ? "var(--status-warning)"
        : tone === "danger"
          ? "var(--status-error)"
          : "var(--foreground)";
  return (
    <div
      className="min-w-0 rounded-[6px] border px-3 py-2.5"
      style={{ borderColor: "var(--border)" }}
    >
      <div className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </div>
      <div
        className="mt-1 truncate font-mono text-[12px] font-semibold"
        style={{ color }}
      >
        {value}
      </div>
    </div>
  );
}

function Message({
  children,
  tone = "warning",
}: {
  children: React.ReactNode;
  tone?: Tone;
}) {
  const color =
    tone === "danger" ? "var(--status-error)" : "var(--status-warning)";
  const background =
    tone === "danger"
      ? "var(--status-error-bg)"
      : "color-mix(in oklab, var(--status-warning) 10%, transparent)";
  return (
    <div
      className="flex gap-2 rounded-[6px] border px-3 py-2 text-[12px] leading-relaxed"
      style={{
        borderColor: `color-mix(in oklab, ${color} 38%, transparent)`,
        background,
        color,
      }}
      role={tone === "danger" ? "alert" : undefined}
    >
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <div className="min-w-0 break-words">{children}</div>
    </div>
  );
}

function OperationError({ error }: { error: unknown }) {
  if (!error) return null;
  return <Message tone="danger">{errorMessage(error)}</Message>;
}

function RouteCard({
  route,
  health,
}: {
  route: string;
  health: AcquisitionRouteHealth;
}) {
  const ready = Boolean(health.ready);
  const routeTone = ready ? "ready" : health.blocked ? "danger" : "warning";
  return (
    <article
      className="rounded-[6px] border p-3"
      style={{ borderColor: "var(--border)" }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-mono text-[12px] font-semibold uppercase tracking-[0.06em]">
          {route}
        </div>
        <StatusPill
          label={ready ? "ready" : humanize(health.reason, "not ready")}
          tone={routeTone}
        />
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-[11px] sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground">downstream</dt>
          <dd className="mt-0.5 font-mono">
            {humanize(health.downstream, "not configured")}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">client</dt>
          <dd className="mt-0.5">
            <StatusPill
              label={health.client_ready ? "ready" : "not ready"}
              tone={toneForBoolean(health.client_ready)}
            />
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">path</dt>
          <dd className="mt-0.5">
            <StatusPill
              label={health.path_ready ? "ready" : "not ready"}
              tone={toneForBoolean(health.path_ready)}
            />
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">restart</dt>
          <dd className="mt-0.5">
            <StatusPill
              label={health.restart_safe ? "safe" : "manual review"}
              tone={toneForBoolean(health.restart_safe)}
            />
          </dd>
        </div>
      </dl>
      <div
        className="mt-3 flex flex-wrap gap-x-3 gap-y-1 border-t pt-2 font-mono text-[10px] text-muted-foreground"
        style={{ borderColor: "var(--border)" }}
      >
        <span>{asCount(health.configured_provider_count)} configured</span>
        <span>{asCount(health.executable_provider_count)} executable</span>
        <span>{asCount(health.attempted_provider_count)} attempted</span>
      </div>
      {health.last_error && (
        <p
          className="mt-3 break-words border-t pt-2 font-mono text-[10px] text-muted-foreground"
          style={{ borderColor: "var(--border)" }}
        >
          {sanitizeAcquisitionMessage(health.last_error)}
        </p>
      )}
    </article>
  );
}

function WorkerCard({
  worker,
  health,
}: {
  worker: string;
  health: AcquisitionWorkerHealth;
}) {
  const state = health.state || (health.alive ? "live" : "unavailable");
  return (
    <article
      className="rounded-[6px] border p-3"
      style={{ borderColor: "var(--border)" }}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="truncate font-mono text-[11px] uppercase tracking-[0.06em]">
          {worker}
        </div>
        <StatusPill label={humanize(state)} tone={toneForState(state)} />
      </div>
      <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
        <span>
          {health.healthy
            ? "healthy"
            : health.alive
              ? "needs attention"
              : "not live"}
        </span>
        <span className="font-mono">{formatMoment(health.last_heartbeat)}</span>
      </div>
      {health.last_error && (
        <p className="mt-2 break-words font-mono text-[10px] text-muted-foreground">
          {sanitizeAcquisitionMessage(health.last_error)}
        </p>
      )}
    </article>
  );
}

function JobRow({ job }: { job: ScheduledJobHealth }) {
  const status = job.state || job.status || job.dispatch?.state || "waiting";
  const error = job.dispatch?.last_error || job.last_error;
  return (
    <tr className="border-t" style={{ borderColor: "var(--border)" }}>
      <td className="py-2 pr-3 text-[12px] font-medium">{job.name}</td>
      <td className="py-2 pr-3">
        <StatusPill label={humanize(status)} tone={toneForState(status)} />
      </td>
      <td className="hidden py-2 pr-3 font-mono text-[10px] text-muted-foreground sm:table-cell">
        {formatMoment(job.next_run_time)}
      </td>
      <td className="max-w-[180px] py-2 font-mono text-[10px] text-muted-foreground">
        <span className="block truncate">
          {error ? sanitizeAcquisitionMessage(error) : "—"}
        </span>
      </td>
    </tr>
  );
}

function RunCard({ kind, run }: { kind: string; run: AcquisitionRunHealth }) {
  const completion = run.completion?.state || "unknown";
  return (
    <article
      className="rounded-[6px] border p-3"
      style={{ borderColor: "var(--border)" }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-mono text-[11px] uppercase tracking-[0.06em]">
          {kind}
        </div>
        <StatusPill
          label={humanize(completion)}
          tone={toneForState(completion)}
        />
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2 font-mono text-[10px] text-muted-foreground">
        <span>{asCount(run.accepted)} accepted</span>
        <span>{asCount(run.matched)} matched</span>
        <span>{asCount(run.no_match)} no match</span>
        <span>{asCount(run.deferred)} deferred</span>
        <span>{asCount(run.failed)} failed</span>
        <span>{formatAge(run.oldest_backlog)} oldest</span>
      </div>
      {(run.error || run.reason) && (
        <p className="mt-2 break-words font-mono text-[10px] text-muted-foreground">
          {sanitizeAcquisitionMessage(run.error || run.reason)}
        </p>
      )}
    </article>
  );
}

function PreviewSummary({ preview }: { preview: AcquisitionRepairPreview }) {
  const summary = preview.summary;
  return (
    <div className="flex flex-wrap gap-1.5" aria-label="Repair preview summary">
      <StatusPill label={`${asCount(summary.owned)} owned`} tone="ready" />
      <StatusPill
        label={`${asCount(summary.optional_wanted)} optional Wanted`}
        tone="warning"
      />
      <StatusPill label={`${asCount(summary.future)} future`} tone="neutral" />
      <StatusPill
        label={`${asCount(summary.in_flight)} in flight`}
        tone="warning"
      />
      <StatusPill
        label={`${asCount(summary.failed)} failed`}
        tone={asCount(summary.failed) ? "danger" : "neutral"}
      />
      <StatusPill
        label={`${asCount(summary.unknown)} unknown`}
        tone={asCount(summary.unknown) ? "warning" : "neutral"}
      />
    </div>
  );
}

function repairHeading(state: string | null | undefined) {
  switch (state) {
    case "completed":
      return "Repair completed";
    case "needs_review":
      return "Repair needs review";
    case "rolled_back":
      return "Repair rolled back";
    case "rollback_needs_review":
      return "Rollback needs review";
    case "waiting_for_drain":
    case "rollback_waiting_for_drain":
      return "Waiting for acquisition work to drain";
    case "applying":
      return "Repair applying";
    case "rolling_back":
      return "Rollback applying";
    case "confirmed":
      return "Manifest confirmed";
    default:
      return `Repair ${humanize(state)}`;
  }
}

function toRun(
  result: AcquisitionRepairResult | null,
  activeRunId: string | null,
): AcquisitionRepairRun | null {
  if (!result && !activeRunId) return null;
  return {
    run_id: result?.run_id || activeRunId || "",
    state: result?.state || "confirmed",
    item_count: result?.item_count,
    selected_count: result?.selected_count,
    applied_count: result?.applied_count,
    conflict_count: result?.conflict_count,
    rollback_count: result?.rollback_count,
    rollback_conflict_count: result?.rollback_conflict_count,
  };
}

export function AcquisitionHealthTab() {
  const [seriesId, setSeriesId] = useState("");
  const [preview, setPreview] = useState<AcquisitionRepairPreview | null>(null);
  const [selectedOptionalKeys, setSelectedOptionalKeys] = useState<Set<string>>(
    new Set(),
  );
  const [previewAcknowledged, setPreviewAcknowledged] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [pollRepair, setPollRepair] = useState(false);
  const [lastRepairResult, setLastRepairResult] =
    useState<AcquisitionRepairResult | null>(null);
  const [rollbackReason, setRollbackReason] = useState("");
  const [resumeReason, setResumeReason] = useState("");
  const [operatorError, setOperatorError] = useState<string | null>(null);
  const [operatorMessage, setOperatorMessage] = useState<string | null>(null);
  const operations = useAcquisitionHealth(activeRunId, pollRepair);

  const health = operations.health.data;
  const maintenance = health?.maintenance;
  const latestRun = operations.repairRun.data?.run;
  const visibleRun = latestRun || toRun(lastRepairResult, activeRunId);
  const maintenanceBlocked = Boolean(maintenance?.blocked);
  const maintenanceOwnedByActiveRepair = Boolean(
    activeRunId && maintenance?.run_id && maintenance.run_id === activeRunId,
  );
  const blockedByAnotherOperation =
    maintenanceBlocked && !maintenanceOwnedByActiveRepair;
  const repairState = visibleRun?.state;
  const optionalItems = useMemo(
    () => preview?.items.filter((item) => item.optional) || [],
    [preview],
  );
  const previewAlreadyConfirmed = Boolean(
    preview && activeRunId === preview.run_id && lastRepairResult,
  );
  const groupedPreviewItems = useMemo(() => {
    const groups = new Map<string, number>();
    for (const item of preview?.items || []) {
      const reason = humanize(item.reason, "unclassified");
      groups.set(reason, (groups.get(reason) || 0) + 1);
    }
    return [...groups.entries()].sort(([left], [right]) =>
      left.localeCompare(right),
    );
  }, [preview]);

  const queryErrors = [
    operations.health.error,
    operations.jobs.error,
    operations.diagnostics.error,
  ].filter(Boolean);
  const currentMutation = [
    operations.previewRepair,
    operations.confirmRepair,
    operations.applyRepair,
    operations.rollbackRepair,
    operations.markReconciliationReady,
  ].find((mutation) => mutation.isPending);

  const handlePreview = async () => {
    const normalizedSeriesId = seriesId.trim();
    if (!normalizedSeriesId) return;
    setOperatorError(null);
    setOperatorMessage(null);
    setActiveRunId(null);
    setPollRepair(false);
    setLastRepairResult(null);
    try {
      const result =
        await operations.previewRepair.mutateAsync(normalizedSeriesId);
      setPreview(result);
      setSelectedOptionalKeys(
        new Set(
          result.items
            .filter((item) => item.optional && item.selected)
            .map((item) => item.entity_key),
        ),
      );
      setPreviewAcknowledged(false);
      setOperatorMessage(
        "Repair preview is read-only. Review the grouped evidence before confirming it.",
      );
    } catch (error) {
      setPreview(null);
      setOperatorError(errorMessage(error));
    }
  };

  const toggleOptionalItem = (entityKey: string) => {
    setSelectedOptionalKeys((current) => {
      const next = new Set(current);
      if (next.has(entityKey)) next.delete(entityKey);
      else next.add(entityKey);
      return next;
    });
  };

  const handleConfirm = async () => {
    if (!preview || !previewAcknowledged || blockedByAnotherOperation) return;
    setOperatorError(null);
    setOperatorMessage(null);
    try {
      const result = await operations.confirmRepair.mutateAsync({
        runId: preview.run_id,
        previewToken: preview.preview_token,
        fingerprint: preview.fingerprint,
        selectedOptionalKeys: [...selectedOptionalKeys].sort(),
      });
      setActiveRunId(result.run_id);
      setLastRepairResult(result);
      setPollRepair(false);
      setPreviewAcknowledged(false);
      setOperatorMessage(
        "Manifest confirmed. No repair data has changed until you apply this exact manifest.",
      );
    } catch (error) {
      setPollRepair(false);
      setOperatorError(errorMessage(error));
    }
  };

  const handleApply = async () => {
    if (!activeRunId || blockedByAnotherOperation) return;
    setOperatorError(null);
    setOperatorMessage(null);
    setPollRepair(true);
    try {
      const result = await operations.applyRepair.mutateAsync(activeRunId);
      setLastRepairResult(result);
      setOperatorMessage(
        result.state === "completed"
          ? "Repair completed."
          : "Repair started; its durable state is being refreshed.",
      );
    } catch (error) {
      setPollRepair(false);
      setOperatorError(errorMessage(error));
    }
  };

  const handleRollback = async () => {
    if (!activeRunId || !rollbackReason.trim() || blockedByAnotherOperation)
      return;
    setOperatorError(null);
    setOperatorMessage(null);
    setPollRepair(true);
    try {
      const result = await operations.rollbackRepair.mutateAsync({
        runId: activeRunId,
        reason: rollbackReason.trim(),
      });
      setLastRepairResult(result);
      setOperatorMessage(
        "Conditional rollback started; its durable state is being refreshed.",
      );
    } catch (error) {
      setPollRepair(false);
      setOperatorError(errorMessage(error));
    }
  };

  const handleResume = async () => {
    if (!resumeReason.trim() || maintenanceBlocked || !health?.viable_route)
      return;
    setOperatorError(null);
    setOperatorMessage(null);
    try {
      const result = await operations.markReconciliationReady.mutateAsync(
        resumeReason.trim(),
      );
      const replayed = result.runtime?.replayed;
      setOperatorMessage(
        replayed
          ? `Automatic acquisition resumed. Replayed ${asCount(replayed.search)} search and ${asCount(replayed.refresh)} refresh obligations.`
          : "Automatic acquisition resumed. Refreshing health now.",
      );
      setResumeReason("");
    } catch (error) {
      setOperatorError(errorMessage(error));
    }
  };

  const isLoading =
    operations.health.isLoading ||
    operations.jobs.isLoading ||
    operations.diagnostics.isLoading;

  return (
    <div className="space-y-6">
      <SettingGroup
        title="Acquisition health"
        description="Live, sanitized readiness for routes, durable workers, and repair maintenance."
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="grid min-w-0 flex-1 grid-cols-1 gap-2 sm:grid-cols-3">
            <Metric
              label="build"
              value={operations.diagnostics.data?.build?.id || "unknown"}
              tone={
                operations.diagnostics.data?.build?.verified
                  ? "ready"
                  : "warning"
              }
            />
            <Metric
              label="maintenance"
              value={maintenanceBlocked ? "blocked" : "clear"}
              tone={maintenanceBlocked ? "warning" : "ready"}
            />
            <Metric
              label="route readiness"
              value={health?.viable_route ? "ready" : "not ready"}
              tone={health?.viable_route ? "ready" : "danger"}
            />
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void operations.refresh()}
            disabled={isLoading || Boolean(currentMutation)}
            title="Refresh acquisition health"
          >
            <RefreshCw className={isLoading ? "animate-spin" : ""} />
            Refresh
          </Button>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          {operations.diagnostics.data?.build?.verified ? (
            <span className="inline-flex items-center gap-1">
              <ShieldCheck className="h-3.5 w-3.5 text-[var(--status-success)]" />
              Verified build
            </span>
          ) : (
            <span className="inline-flex items-center gap-1">
              <CircleAlert className="h-3.5 w-3.5 text-[var(--status-warning)]" />
              Build commit is not verified
            </span>
          )}
          {operations.diagnostics.data?.build?.commit && (
            <span className="font-mono">
              {sanitizeAcquisitionMessage(
                operations.diagnostics.data.build.commit,
              )}
            </span>
          )}
          {maintenance?.active_leases !== undefined &&
            maintenance?.active_leases !== null && (
              <span>
                {maintenance.active_leases} active lease
                {maintenance.active_leases === 1 ? "" : "s"}
              </span>
            )}
          {maintenance?.drained === false && <span>draining active work</span>}
          {health?.blocked_producer_count !== undefined && (
            <span>
              {asCount(health.blocked_producer_count)} blocked producer
              {asCount(health.blocked_producer_count) === 1 ? "" : "s"}
            </span>
          )}
        </div>

        {maintenanceBlocked && (
          <div className="mt-3">
            <Message tone={blockedByAnotherOperation ? "danger" : "warning"}>
              Acquisition maintenance is active
              {maintenance?.reason
                ? `: ${sanitizeAcquisitionMessage(maintenance.reason)}`
                : "."}
              {blockedByAnotherOperation
                ? " Mutating controls are disabled until the owning operation releases it."
                : " This repair owns the fence; wait for durable progress before another action."}
            </Message>
          </div>
        )}
        {queryErrors.length > 0 && (
          <div className="mt-3 space-y-2">
            {queryErrors.map((error, index) => (
              <OperationError key={index} error={error} />
            ))}
          </div>
        )}
      </SettingGroup>

      <SettingGroup
        title="Route readiness"
        description="A ready route has a configured provider, client, path, and restart-safe handoff correlation."
      >
        {health?.routes && Object.keys(health.routes).length > 0 ? (
          <div className="grid gap-3 md:grid-cols-2">
            {Object.entries(health.routes)
              .sort(([left], [right]) => left.localeCompare(right))
              .map(([route, routeHealth]) => (
                <RouteCard key={route} route={route} health={routeHealth} />
              ))}
          </div>
        ) : (
          <Message>
            No route readiness has been reported yet. Configure a supported
            provider and download client, then refresh.
          </Message>
        )}
      </SettingGroup>

      <SettingGroup
        title="Workers, schedules, and backlog"
        description="Scheduler dispatch is separate from item completion, so a job can run while acquisition still needs attention."
      >
        <div className="space-y-4">
          <section aria-label="Worker liveness">
            <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.07em] text-muted-foreground">
              <Clock3 className="h-3.5 w-3.5" />
              Worker liveness
            </div>
            {health?.workers && Object.keys(health.workers).length > 0 ? (
              <div className="grid gap-3 sm:grid-cols-2">
                {Object.entries(health.workers).map(
                  ([worker, workerHealth]) => (
                    <WorkerCard
                      key={worker}
                      worker={worker}
                      health={workerHealth}
                    />
                  ),
                )}
              </div>
            ) : (
              <p className="text-[12px] text-muted-foreground">
                No worker heartbeat is available yet.
              </p>
            )}
          </section>

          <section aria-label="Scheduled jobs">
            <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.07em] text-muted-foreground">
              <LoaderCircle className="h-3.5 w-3.5" />
              Scheduled jobs
            </div>
            {operations.jobs.data?.jobs?.length ? (
              <div
                className="overflow-x-auto rounded-[6px] border"
                style={{ borderColor: "var(--border)" }}
              >
                <table className="w-full min-w-[520px] text-left">
                  <thead className="text-[10px] uppercase tracking-[0.07em] text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 font-medium">job</th>
                      <th className="px-3 py-2 font-medium">status</th>
                      <th className="hidden px-3 py-2 font-medium sm:table-cell">
                        next run
                      </th>
                      <th className="px-3 py-2 font-medium">last error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {operations.jobs.data.jobs.map((job) => (
                      <JobRow key={job.id} job={job} />
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-[12px] text-muted-foreground">
                No scheduler jobs are available.
              </p>
            )}
          </section>

          <section aria-label="Durable acquisition runs">
            <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.07em] text-muted-foreground">
              <CheckCircle2 className="h-3.5 w-3.5" />
              Durable acquisition runs
            </div>
            {health?.acquisition &&
            Object.keys(health.acquisition).length > 0 ? (
              <div className="grid gap-3 md:grid-cols-2">
                {Object.entries(health.acquisition).map(([kind, run]) => (
                  <RunCard key={kind} kind={kind} run={run} />
                ))}
              </div>
            ) : (
              <p className="text-[12px] text-muted-foreground">
                No durable acquisition runs have been recorded yet.
              </p>
            )}
          </section>
        </div>
      </SettingGroup>

      <SettingGroup
        title="Evidence-driven repair"
        description="Create a read-only series preview first. The one-time token and immutable fingerprint are held only in this browser session and never displayed."
      >
        <div className="space-y-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
            <div className="min-w-0 flex-1">
              <label
                htmlFor="repair-series-id"
                className="mb-1 block text-[12px] font-medium"
              >
                Series ID
              </label>
              <input
                id="repair-series-id"
                value={seriesId}
                onChange={(event) => setSeriesId(event.target.value)}
                inputMode="numeric"
                placeholder="e.g. 160294"
                className="h-9 w-full rounded-md border bg-background px-3 font-mono text-sm"
                style={{ borderColor: "var(--border)" }}
              />
            </div>
            <Button
              type="button"
              onClick={() => void handlePreview()}
              disabled={!seriesId.trim() || operations.previewRepair.isPending}
            >
              {operations.previewRepair.isPending && (
                <LoaderCircle className="animate-spin" />
              )}
              Preview repair
            </Button>
          </div>
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            Preview does not alter issue status, files, queues, or aggregates.
            It remains available while another maintenance operation blocks
            writes.
          </p>

          {preview && (
            <article
              className="space-y-3 rounded-[6px] border p-3.5"
              style={{
                borderColor: "var(--border)",
                background: "var(--secondary)",
              }}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-[13px] font-semibold">Repair preview</h3>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                    Run {preview.run_id}
                  </p>
                </div>
                <PreviewSummary preview={preview} />
              </div>
              <div className="grid gap-2 text-[11px] sm:grid-cols-2 lg:grid-cols-3">
                {groupedPreviewItems.map(([reason, count]) => (
                  <div
                    key={reason}
                    className="rounded border px-2.5 py-2"
                    style={{
                      borderColor: "var(--border)",
                      background: "var(--background)",
                    }}
                  >
                    <span className="font-mono">{count}</span> {reason}
                  </div>
                ))}
              </div>
              {optionalItems.length > 0 && (
                <fieldset
                  className="space-y-2 border-t pt-3"
                  style={{ borderColor: "var(--border)" }}
                >
                  <legend className="px-0 text-[12px] font-medium">
                    Optional Wanted candidates
                  </legend>
                  <p className="text-[11px] text-muted-foreground">
                    These are not selected by default. Select only released,
                    missing rows you explicitly want to mark Wanted.
                  </p>
                  {optionalItems.map((item) => (
                    <label
                      key={item.entity_key}
                      className="flex cursor-pointer items-start gap-2 rounded border px-2.5 py-2 text-[11px]"
                      style={{
                        borderColor: "var(--border)",
                        background: "var(--background)",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={selectedOptionalKeys.has(item.entity_key)}
                        disabled={previewAlreadyConfirmed}
                        onChange={() => toggleOptionalItem(item.entity_key)}
                        aria-label={`Select optional ${item.entity_key}`}
                      />
                      <span className="min-w-0">
                        <span className="font-mono">{item.entity_key}</span>
                        <span className="ml-2 text-muted-foreground">
                          {humanize(item.reason)} · {humanize(item.fulfillment)}
                        </span>
                      </span>
                    </label>
                  ))}
                </fieldset>
              )}
              <label
                className="flex items-start gap-2 rounded border px-2.5 py-2 text-[11px]"
                style={{
                  borderColor: "var(--border)",
                  background: "var(--background)",
                }}
              >
                <input
                  type="checkbox"
                  checked={previewAcknowledged}
                  disabled={previewAlreadyConfirmed}
                  onChange={(event) =>
                    setPreviewAcknowledged(event.target.checked)
                  }
                />
                <span>
                  I reviewed this immutable preview and want to freeze it
                </span>
              </label>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void handleConfirm()}
                  disabled={
                    !previewAcknowledged ||
                    previewAlreadyConfirmed ||
                    blockedByAnotherOperation ||
                    operations.confirmRepair.isPending
                  }
                >
                  {operations.confirmRepair.isPending && (
                    <LoaderCircle className="animate-spin" />
                  )}
                  Confirm preview
                </Button>
                {blockedByAnotherOperation && (
                  <span className="text-[11px] text-muted-foreground">
                    A different maintenance operation owns the write fence.
                  </span>
                )}
                {previewAlreadyConfirmed && (
                  <span className="text-[11px] text-muted-foreground">
                    This preview is already frozen into the manifest below.
                  </span>
                )}
              </div>
            </article>
          )}

          {visibleRun && (
            <article
              className="space-y-3 rounded-[6px] border p-3.5"
              style={{ borderColor: "var(--border)" }}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-[13px] font-semibold">
                    {repairHeading(repairState)}
                  </h3>
                  <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                    {visibleRun.run_id}
                  </p>
                </div>
                <StatusPill
                  label={humanize(repairState)}
                  tone={toneForState(repairState)}
                />
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Metric
                  label="selected"
                  value={asCount(visibleRun.selected_count)}
                />
                <Metric
                  label="applied"
                  value={asCount(visibleRun.applied_count)}
                  tone={
                    asCount(visibleRun.conflict_count) ? "warning" : "ready"
                  }
                />
                <Metric
                  label="conflicts"
                  value={asCount(visibleRun.conflict_count)}
                  tone={
                    asCount(visibleRun.conflict_count) ? "danger" : "neutral"
                  }
                />
                <Metric
                  label="rolled back"
                  value={asCount(visibleRun.rollback_count)}
                />
              </div>
              {APPLYABLE_REPAIR_STATES.has(repairState || "") && (
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    onClick={() => void handleApply()}
                    disabled={
                      blockedByAnotherOperation ||
                      operations.applyRepair.isPending
                    }
                  >
                    {operations.applyRepair.isPending && (
                      <LoaderCircle className="animate-spin" />
                    )}
                    Apply confirmed repair
                  </Button>
                  <span className="text-[11px] text-muted-foreground">
                    Apply uses the confirmed manifest only and fences new
                    acquisition work first.
                  </span>
                </div>
              )}
              {ROLLBACKABLE_REPAIR_STATES.has(repairState || "") && (
                <div
                  className="flex flex-col gap-2 border-t pt-3 sm:flex-row sm:items-end"
                  style={{ borderColor: "var(--border)" }}
                >
                  <div className="min-w-0 flex-1">
                    <label
                      htmlFor="repair-rollback-reason"
                      className="mb-1 block text-[12px] font-medium"
                    >
                      Rollback reason
                    </label>
                    <input
                      id="repair-rollback-reason"
                      value={rollbackReason}
                      onChange={(event) =>
                        setRollbackReason(event.target.value)
                      }
                      placeholder="Why this conditional rollback is needed"
                      className="h-9 w-full rounded-md border bg-background px-3 text-sm"
                      style={{ borderColor: "var(--border)" }}
                    />
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => void handleRollback()}
                    disabled={
                      !rollbackReason.trim() ||
                      blockedByAnotherOperation ||
                      operations.rollbackRepair.isPending
                    }
                  >
                    {operations.rollbackRepair.isPending && (
                      <LoaderCircle className="animate-spin" />
                    )}
                    Conditional rollback
                  </Button>
                </div>
              )}
              <OperationError error={operations.repairRun.error} />
            </article>
          )}
          <OperationError
            error={
              operations.previewRepair.error ||
              operations.confirmRepair.error ||
              operations.applyRepair.error ||
              operations.rollbackRepair.error ||
              operatorError
            }
          />
        </div>
      </SettingGroup>

      <SettingGroup
        title="Resume automatic acquisition"
        description="Only release automatic work after repair is complete, routes are ready, and you have recorded why this instance is safe to resume."
      >
        <div className="space-y-2">
          <label
            htmlFor="reconciliation-reason"
            className="text-[12px] font-medium"
          >
            Resume reason
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              id="reconciliation-reason"
              value={resumeReason}
              onChange={(event) => setResumeReason(event.target.value)}
              placeholder="e.g. repair run reviewed and one supported route is ready"
              className="h-9 min-w-0 flex-1 rounded-md border bg-background px-3 text-sm"
              style={{ borderColor: "var(--border)" }}
            />
            <Button
              type="button"
              variant="outline"
              onClick={() => void handleResume()}
              disabled={
                !resumeReason.trim() ||
                maintenanceBlocked ||
                !health?.viable_route ||
                operations.markReconciliationReady.isPending
              }
            >
              {operations.markReconciliationReady.isPending && (
                <LoaderCircle className="animate-spin" />
              )}
              Resume automatic acquisition
            </Button>
          </div>
          {maintenanceBlocked && (
            <p className="text-[11px] text-muted-foreground">
              Automatic acquisition cannot be resumed while maintenance is
              active.
            </p>
          )}
          {!maintenanceBlocked && !health?.viable_route && (
            <p className="text-[11px] text-muted-foreground">
              Configure at least one restart-safe route before resuming
              automatic acquisition.
            </p>
          )}
        </div>
      </SettingGroup>

      {operatorMessage && (
        <div
          className="flex items-start gap-2 rounded-[6px] border px-3 py-2 text-[12px]"
          style={{
            borderColor:
              "color-mix(in oklab, var(--status-success) 35%, transparent)",
            background:
              "color-mix(in oklab, var(--status-success) 10%, transparent)",
            color: "var(--status-success)",
          }}
          aria-live="polite"
        >
          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {sanitizeAcquisitionMessage(operatorMessage)}
        </div>
      )}
      {!isLoading && !health && (
        <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <CircleX className="h-3.5 w-3.5" />
          Health data is unavailable. You can still create a read-only repair
          preview once the server responds.
        </div>
      )}
    </div>
  );
}
