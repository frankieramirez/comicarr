import { ph, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import { useToast } from "@/components/ui/toast";
import {
  useConnections,
  useDeprecations,
  useJobsHealth,
  useSearchHealth,
  useTestConnection,
} from "@/hooks/useAcquisitionHealth";
import type { DeprecationInUse } from "@/hooks/useAcquisitionHealth";
import { getErrorMessage } from "@/lib/api";
import {
  TONE_COLOR,
  ago,
  connectionRows,
  jobRows,
  until,
  type ConnectionRow,
  type HealthTone,
  type JobRow,
} from "@/lib/healthRows";
import { cn } from "@/lib/utils";
import { useRunJobOutcome } from "@/hooks/useRunJobOutcome";
import { JobResultText } from "@/components/activity/health/JobResultText";

const JOB_COLS =
  "grid-cols-[minmax(0,1fr)_auto] md:grid-cols-[minmax(160px,1.2fr)_110px_110px_minmax(0,2fr)_96px]";
const DEPRECATION_COLS =
  "grid-cols-[minmax(0,1fr)_auto] md:grid-cols-[minmax(160px,1.2fr)_minmax(0,2fr)_110px_96px]";
const CONNECTION_COLS =
  "grid-cols-[minmax(0,1fr)_auto] md:grid-cols-[minmax(160px,1.2fr)_110px_110px_minmax(0,2fr)_96px]";

function Dot({ tone }: { tone: HealthTone }) {
  return (
    <span
      aria-hidden="true"
      data-testid="health-dot"
      className="size-1.5 shrink-0 rounded-full"
      style={{ background: TONE_COLOR[tone] }}
    />
  );
}

function SectionHeading({ title, meta }: { title: string; meta: string }) {
  return (
    <h2 className="flex items-baseline gap-2 pb-3 text-[15px] font-semibold text-foreground">
      {title}
      <span className="font-mono text-xs font-normal text-muted-foreground">
        {meta}
      </span>
    </h2>
  );
}

function ColumnHeads({ cols, heads }: { cols: string; heads: string[] }) {
  return (
    <div
      className={`grid ${cols} gap-x-3 border-b border-border-subtle px-4 pb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground max-md:hidden`}
    >
      {heads.map((head, index) => (
        <span
          key={index}
          className={index === heads.length - 1 ? "sr-only" : ""}
        >
          {head}
        </span>
      ))}
    </div>
  );
}

function JobLine({ job }: { job: JobRow }) {
  const { start, running } = useRunJobOutcome(job);
  return (
    <div
      data-testid="health-job"
      className={cn(
        `grid ${JOB_COLS} min-h-10 items-center gap-x-3 border-b border-border-subtle px-4 py-1.5 text-[13px]`,
        job.failing && "border-s-2 bg-surface-1",
      )}
      style={
        job.failing ? { borderLeftColor: "var(--status-error)" } : undefined
      }
    >
      <span className="flex min-w-0 items-center gap-2">
        <Dot tone={job.tone} />
        <span className="truncate text-foreground">{job.label}</span>
      </span>
      <span className="font-mono text-xs text-foreground-2 max-md:hidden">
        {ago(job.lastRun)}
      </span>
      <span className="font-mono text-xs text-foreground-2 max-md:hidden">
        {until(job.nextRun)}
      </span>
      <JobResultText
        text={job.result}
        failing={job.failing}
        className="max-md:col-span-2 max-md:row-start-2 max-md:ps-3.5"
      />
      <span className="flex justify-end max-md:col-start-2 max-md:row-start-1">
        {job.runnable && (
          <Button
            type="button"
            size="compact"
            variant={job.failing ? "default" : "ghost"}
            aria-label={t`Run ${ph({ label: job.label })} now`}
            disabled={running || job.busy}
            onClick={() => void start()}
          >
            {running ? t`Running…` : job.busy ? t`Queued` : t`Run now`}
          </Button>
        )}
      </span>
    </div>
  );
}

function ConnectionLine({ row }: { row: ConnectionRow }) {
  const test = useTestConnection();
  const { addToast } = useToast();
  const many = row.key === "indexers";
  const start = async () => {
    try {
      const result = await test.mutateAsync(row.testKey);
      if ("connections" in result) return;
      if (result.ok === false)
        addToast({
          type: "error",
          message: result.result
            ? t`${ph({ label: result.label })}: ${ph({ result: result.result })}`
            : t`${ph({ label: result.label })}: check failed`,
        });
    } catch (err) {
      addToast({ type: "error", message: getErrorMessage(err) });
    }
  };
  return (
    <div
      data-testid="health-connection"
      className={`grid ${CONNECTION_COLS} min-h-10 items-center gap-x-3 border-b border-border-subtle px-4 py-1.5 text-[13px]`}
    >
      <span className="flex min-w-0 items-center gap-2">
        <Dot tone={row.tone} />
        <span className="truncate text-foreground">{row.label}</span>
      </span>
      <span className="font-mono text-xs text-foreground-2 max-md:hidden">
        {test.isPending ? "…" : row.response}
      </span>
      <span className="font-mono text-xs text-foreground-2 max-md:hidden">
        {ago(row.lastChecked)}
      </span>
      <span
        className="truncate text-foreground-2 max-md:col-span-2 max-md:row-start-2 max-md:ps-3.5"
        title={row.result}
      >
        {test.isPending ? t`Checking…` : row.result}
      </span>
      <span className="flex justify-end max-md:col-start-2 max-md:row-start-1">
        {row.testKey ? (
          <Button
            type="button"
            size="compact"
            variant="ghost"
            aria-label={
              many ? t`Test all indexers` : t`Test ${ph({ label: row.label })}`
            }
            disabled={test.isPending}
            onClick={() => void start()}
          >
            {many ? t`Test all` : t`Test`}
          </Button>
        ) : (
          <Link
            to={row.settings}
            className="px-2 text-[13px] text-foreground-2 hover:text-foreground"
          >
            <Trans>Settings</Trans>
          </Link>
        )}
      </span>
    </div>
  );
}

function DeprecationLine({ entry }: { entry: DeprecationInUse }) {
  return (
    <div
      data-testid="health-deprecation"
      className={`grid ${DEPRECATION_COLS} min-h-10 items-center gap-x-3 border-b border-border-subtle px-4 py-1.5 text-[13px]`}
    >
      <span className="flex min-w-0 items-center gap-2">
        <Dot tone="warn" />
        <span className="text-foreground">{entry.name}</span>
      </span>
      <span className="text-foreground-2 max-md:col-span-2 max-md:row-start-2 max-md:ps-3.5">
        {entry.replacement}
      </span>
      <span className="font-mono text-xs text-foreground-2 max-md:hidden">
        {entry.removable_from}
      </span>
      <span className="flex justify-end max-md:col-start-2 max-md:row-start-1">
        <a
          href={entry.docs_url}
          target="_blank"
          rel="noreferrer"
          aria-label={t`Read about ${ph({ name: entry.name })}`}
          className="px-2 text-[13px] text-foreground-2 hover:text-foreground"
        >
          <Trans>Details</Trans>
        </a>
      </span>
    </div>
  );
}

/** Only installs that use a deprecated feature see this section (ADR-0006). */
function DeprecationsSection() {
  const { data } = useDeprecations();
  const entries = data?.deprecations ?? [];
  if (entries.length === 0) return null;
  return (
    <section aria-labelledby="health-deprecations" className="mb-8">
      <div id="health-deprecations">
        <SectionHeading
          title={t`Deprecated features in use`}
          meta={t`${ph({ length: entries.length })} still working`}
        />
      </div>
      <ColumnHeads
        cols={DEPRECATION_COLS}
        heads={[t`Feature`, t`Use instead`, t`Removable from`, t`Docs`]}
      />
      {entries.map((entry) => (
        <DeprecationLine key={entry.id} entry={entry} />
      ))}
    </section>
  );
}

/**
 * Activity > Health (v2 design 08): background jobs and the connections
 * downloads depend on, each with a plain answer to "is it working?".
 */
export default function HealthView() {
  const jobs = useJobsHealth();
  const health = useSearchHealth();
  const rows = jobRows(jobs.data?.jobs ?? []);
  const failing = rows.filter((row) => row.failing).length;
  const checks = useConnections();
  const connections = connectionRows(
    health.data,
    checks.data?.connections ?? [],
  );
  const reachable = connections.filter((row) => row.tone === "ok").length;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-4 pt-4 pb-8 md:px-8">
      <DeprecationsSection />
      <section aria-labelledby="health-jobs">
        <div id="health-jobs">
          <SectionHeading
            title={t`Background jobs`}
            meta={
              jobs.data
                ? failing > 0
                  ? t`${failing} of ${ph({ length: rows.length })} failing`
                  : t`${ph({ length: rows.length })} running on schedule`
                : ""
            }
          />
        </div>
        {jobs.isPending ? (
          <div className="space-y-2">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        ) : jobs.error ? (
          <ErrorDisplay
            error={jobs.error}
            title={t`Unable to load background jobs`}
            onRetry={() => void jobs.refetch()}
          />
        ) : rows.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">
            <Trans>
              The scheduler isn't running, so no background jobs are scheduled.
            </Trans>
          </p>
        ) : (
          <div>
            <ColumnHeads
              cols={JOB_COLS}
              heads={[
                t`Job`,
                t`Last run`,
                t`Next run`,
                t`Last result`,
                t`Actions`,
              ]}
            />
            {rows.map((job) => (
              <JobLine key={job.id} job={job} />
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="health-connections" className="mt-8">
        <div id="health-connections">
          <SectionHeading
            title={t`Connections`}
            meta={
              health.data
                ? t`${reachable} of ${ph({ length: connections.length })} reachable`
                : ""
            }
          />
        </div>
        {health.isPending ? (
          <div className="space-y-2">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        ) : health.error ? (
          <ErrorDisplay
            error={health.error}
            title={t`Unable to load connections`}
            onRetry={() => void health.refetch()}
          />
        ) : connections.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">
            <Trans>
              No download client or indexer is set up yet.{" "}
              <Link
                to="/settings?section=clients"
                className="text-foreground underline underline-offset-2"
              >
                Add one in Settings
              </Link>
              .
            </Trans>
          </p>
        ) : (
          <div>
            <ColumnHeads
              cols={CONNECTION_COLS}
              heads={[
                t`Connection`,
                t`Response`,
                t`Last checked`,
                t`Result`,
                t`Actions`,
              ]}
            />
            {connections.map((row) => (
              <ConnectionLine key={row.key} row={row} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
