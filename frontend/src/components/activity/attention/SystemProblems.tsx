import { ph, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { AlertTriangle, KeyRound, Plug, Search } from "lucide-react";
import { Link } from "react-router-dom";
import { Button, buttonVariants } from "@/components/ui/button";
import { JobResultText } from "@/components/activity/health/JobResultText";
import { useRunJobOutcome } from "@/hooks/useRunJobOutcome";
import type { SystemProblems } from "@/hooks/useSystemProblems";
import type { JobRow } from "@/lib/healthRows";
import { cn } from "@/lib/utils";

/**
 * Problems that stop work for the whole library rather than for one issue
 * (#1493): a setup gap that stops every search, a missing Comic Vine key, and
 * a scheduled job whose last run failed. Before this, Needs you listed only
 * issue-level problems and said "Nothing needs your attention" while the RSS
 * check failed every run.
 */

const HEALTH_HREF = "/activity?view=health";
const SETTINGS_KEYS = "/settings?section=api";

function Row({
  icon: Icon,
  headline,
  detail,
  actions,
}: {
  icon: typeof Search;
  headline: string;
  detail: React.ReactNode;
  actions: React.ReactNode;
}) {
  return (
    <li
      data-testid="attention-system-problem"
      className="flex flex-wrap items-start gap-x-3.5 gap-y-2 border-b border-border-subtle px-4 py-3 last:border-b-0"
    >
      <Icon
        className="mt-0.5 size-[18px] shrink-0"
        style={{ color: "var(--status-error)" }}
        aria-hidden="true"
      />
      <div className="flex min-w-0 flex-1 basis-[calc(100%-32px)] flex-col sm:basis-0">
        <span className="text-sm font-medium text-foreground">{headline}</span>
        <span className="flex min-w-0 text-[13px] text-foreground-2">
          {detail}
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-2 max-sm:ms-8">
        {actions}
      </div>
    </li>
  );
}

function FixLink({ to, label }: { to: string; label: string }) {
  return (
    <Link
      to={to}
      className={cn(buttonVariants({ variant: "outline", size: "toolbar" }))}
    >
      {label}
    </Link>
  );
}

function FailingJobRow({ job }: { job: JobRow }) {
  const { start, running } = useRunJobOutcome(job);
  return (
    <Row
      icon={AlertTriangle}
      headline={t`${ph({ label: job.label })} is failing`}
      detail={<JobResultText text={job.result} failing />}
      actions={
        <>
          {job.runnable && (
            <Button
              type="button"
              size="toolbar"
              variant="default"
              aria-label={t`Run ${ph({ label: job.label })} now`}
              disabled={running || job.busy}
              onClick={() => void start()}
            >
              {running ? t`Running…` : t`Run now`}
            </Button>
          )}
          <FixLink to={HEALTH_HREF} label={t`Open Health`} />
        </>
      }
    />
  );
}

export function SystemProblemList({ problems }: { problems: SystemProblems }) {
  if (problems.count === 0) return null;
  return (
    <section
      aria-label={t`Problems that stop all downloads`}
      className="mb-4 overflow-hidden rounded-lg border border-border bg-surface-1"
    >
      <h2 className="border-b border-border-subtle px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
        <Trans>Stops work for the whole library</Trans>
      </h2>
      <ul>
        {problems.blockers.map((blocker) => (
          <Row
            key={blocker.key}
            icon={blocker.key === "indexer" ? Search : Plug}
            headline={blocker.headline}
            detail={blocker.detail}
            actions={<FixLink to={blocker.fix.to} label={blocker.fix.label} />}
          />
        ))}
        {problems.keyMissing && (
          <Row
            icon={KeyRound}
            headline={t`No Comic Vine API key, so comics can't be searched or refreshed`}
            detail={t`Add a free key from comicvine.gamespot.com in Sources and keys.`}
            actions={
              <FixLink to={SETTINGS_KEYS} label={t`Open Sources and keys`} />
            }
          />
        )}
        {problems.failingJobs.map((job) => (
          <FailingJobRow key={job.id} job={job} />
        ))}
      </ul>
    </section>
  );
}
