import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { CircleX, FileWarning, MoreHorizontal, Wrench } from "lucide-react";
import {
  actionLabel,
  stageAccent,
  type AttentionCause,
  type BandAction,
} from "@/components/activity/timeline";
import { StopWantingDialog } from "@/components/activity/attention/StopWantingDialog";
import {
  PanelUnavailable,
  SectionHeader,
} from "@/components/dashboard/DashboardPanel";
import { Skeleton } from "@/components/ui/skeleton";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { causeSubline, plural, seriesList } from "@/lib/attentionCause";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useToast } from "@/components/ui/toast";
import {
  useActivityBand,
  useBandBatchResolution,
  type BandBatchResult,
} from "@/hooks/useActivity";

/**
 * Needs-attention on the dashboard (docs/architecture/dashboard-spec.md §3.2).
 *
 * This is the *actionable* half of failure visibility — the health band covers
 * infrastructure; this surface shows the specific releases that already need a
 * human decision. It reads `GET /api/attention` (group envelope, not rows)
 * and resolves through the same `POST /api/attention/resolve` command the
 * triage route uses, so an action here has the same effect and the count
 * refreshes without a manual reload.
 *
 * Zero groups is a single quiet "Nothing needs you" line, not an empty card.
 * That sentence is only trustworthy alongside the health band's
 * last-successful-search line.
 */

const TRIAGE_HREF = "/activity/attention";

function batchSummary(result: BandBatchResult): string {
  const verb = actionLabel(result.action);
  const head =
    result.succeeded === result.processed
      ? `${verb} — ${result.succeeded} ${
          result.succeeded === 1 ? "issue" : "issues"
        }.`
      : `${verb} ${result.succeeded} of ${result.processed} — ${
          result.failed
        } still ${result.failed === 1 ? "needs" : "need"} attention.`;
  if (!result.capped) return head;
  return `${head} ${result.skipped_for_cap} left for another go (max ${result.cap} at a time).`;
}

/** Causes shown before the rest fold into one line (v2 dashboard). */
const CAUSE_PREVIEW = 3;

function causeActionText(action: BandAction, count: number) {
  if (action === "stop_wanting") {
    return count > 1 ? `${actionLabel(action)}…` : actionLabel(action);
  }
  return count > 1
    ? `${actionLabel(action)} all ${count}`
    : actionLabel(action);
}

const CAUSE_ICONS = {
  settings: Wrench,
  file: FileWarning,
  failed: CircleX,
} as const;

function CauseRow({
  cause,
  busy,
  primaryRow,
  onAction,
}: {
  cause: AttentionCause;
  busy: boolean;
  /** The first row carries the view's one filled button. */
  primaryRow: boolean;
  onAction: (action: BandAction, cause: AttentionCause) => void;
}) {
  const navigate = useNavigate();
  const Icon = CAUSE_ICONS[cause.icon as keyof typeof CAUSE_ICONS] ?? CircleX;
  const mixed = cause.available_actions.length === 0;
  const firstGroup = cause.series[0]?.group_key;
  const triageHref =
    cause.series.length === 1 && firstGroup
      ? `${TRIAGE_HREF}?group=${encodeURIComponent(firstGroup)}`
      : TRIAGE_HREF;
  // A settings fix clears the whole cause, so it leads and every
  // per-issue action moves to the menu.
  const [primary, ...rest] = cause.fix ? [] : cause.available_actions;
  const menuActions = cause.fix ? cause.available_actions : rest;
  const filled = primaryRow ? "default" : "outline";

  return (
    <div
      className="flex flex-wrap items-center gap-x-3.5 gap-y-2.5 border-b border-border-subtle py-3 max-sm:items-start"
      data-testid="needs-attention-cause"
    >
      <Icon
        className="size-[18px] shrink-0 self-start mt-0.5"
        style={{ color: stageAccent(cause.stage) }}
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1 max-sm:basis-[calc(100%-32px)]">
        <div className="text-sm font-medium text-foreground sm:truncate">
          {cause.headline}
        </div>
        <div className="text-[13px] text-foreground-2 sm:truncate">
          {causeSubline(cause)}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2 max-sm:ml-8">
        {cause.fix ? (
          <Link
            to={cause.fix.href}
            className={cn(buttonVariants({ variant: filled, size: "toolbar" }))}
          >
            {cause.fix.label}
          </Link>
        ) : mixed ? (
          <Link
            to={triageHref}
            className={cn(
              buttonVariants({ variant: "outline", size: "toolbar" }),
            )}
          >
            Open triage
          </Link>
        ) : (
          <Button
            type="button"
            variant={filled}
            size="toolbar"
            disabled={busy}
            onClick={() => onAction(primary, cause)}
          >
            {causeActionText(primary, cause.member_count)}
          </Button>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                disabled={busy}
                aria-label={`More actions for ${cause.headline}`}
              >
                <MoreHorizontal />
              </Button>
            }
          />
          <DropdownMenuContent align="end">
            {menuActions.map((action) => (
              <DropdownMenuItem
                key={action}
                onClick={() => onAction(action, cause)}
              >
                {causeActionText(action, cause.member_count)}
              </DropdownMenuItem>
            ))}
            <DropdownMenuItem onClick={() => navigate(triageHref)}>
              Open in Activity
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}

function seriesIdentity(series: AttentionCause["series"][number]) {
  return series.comicid ?? series.group_key;
}

function distinctSeries(causes: AttentionCause[]) {
  return new Set(causes.flatMap((c) => c.series.map(seriesIdentity))).size;
}

export default function NeedsAttentionBand() {
  const band = useActivityBand();
  const batch = useBandBatchResolution();
  const { addToast } = useToast();
  const [confirming, setConfirming] = useState<{
    releaseKeys: string[];
    seriesLabel?: string;
  } | null>(null);

  const runAction = async (action: BandAction, releaseKeys: string[]) => {
    if (releaseKeys.length === 0) return;
    try {
      const result = await batch.mutateAsync({ action, releaseKeys });
      addToast({
        type: result.partial ? "info" : "success",
        message: batchSummary(result),
      });
    } catch (err) {
      addToast({
        type: "error",
        message:
          err instanceof Error
            ? err.message
            : `Unable to ${actionLabel(action).toLowerCase()} these issues.`,
      });
    }
  };

  const onCauseAction = (action: BandAction, cause: AttentionCause) => {
    const releaseKeys = cause.release_keys;
    if (action === "stop_wanting" && releaseKeys.length >= 2) {
      setConfirming({
        releaseKeys,
        seriesLabel: seriesList(cause.series.map((s) => s.series_label)),
      });
      return;
    }
    void runAction(action, releaseKeys);
  };

  if (band.isPending) {
    return (
      <section data-testid="needs-attention-loading">
        <SectionHeader title="Needs you" meta="…" />
        <Skeleton aria-hidden="true" className="h-10 w-full rounded-md" />
      </section>
    );
  }

  if (band.isError) {
    return (
      <section>
        <SectionHeader title="Needs you" />
        <PanelUnavailable
          label="Needs attention"
          onRetry={() => void band.refetch()}
          isRetrying={band.isFetching}
        />
      </section>
    );
  }

  const causes = band.data?.causes ?? [];
  const total = band.data?.total ?? 0;
  const memberTotal = band.data?.member_total ?? 0;
  const preview = causes.slice(0, CAUSE_PREVIEW);
  const hidden = causes.slice(CAUSE_PREVIEW);
  const hiddenSeries = distinctSeries(hidden);
  const hiddenIssues = hidden.reduce((n, c) => n + c.member_count, 0);

  if (total === 0) {
    return (
      <section data-testid="needs-attention-empty">
        <SectionHeader title="Needs you" />
        <div className="flex items-center gap-2 py-2 text-sm text-foreground-2">
          <span
            className="size-1.5 rounded-full"
            style={{ background: "var(--status-active)" }}
            aria-hidden="true"
          />
          Nothing needs you
        </div>
      </section>
    );
  }

  return (
    <section aria-label="Needs attention" data-testid="needs-attention-band">
      <SectionHeader
        title="Needs you"
        meta={`${distinctSeries(causes)} series · ${plural(memberTotal, "issue")}`}
        action={{ label: "See all", to: TRIAGE_HREF }}
      />

      <div className="border-t border-border-subtle">
        {preview.map((cause, index) => (
          <CauseRow
            key={cause.cause_key}
            cause={cause}
            primaryRow={index === 0}
            busy={batch.isPending}
            onAction={onCauseAction}
          />
        ))}
        {hidden.length > 0 && (
          <Link
            to={TRIAGE_HREF}
            className="block py-2.5 pl-8 text-[13px] text-foreground-2 hover:text-foreground"
            data-testid="needs-attention-more"
          >
            {hiddenSeries} more series with {plural(hiddenIssues, "issue")}, in
            other causes
          </Link>
        )}
      </div>

      {confirming && (
        <StopWantingDialog
          count={confirming.releaseKeys.length}
          seriesLabel={confirming.seriesLabel}
          busy={batch.isPending}
          onCancel={() => setConfirming(null)}
          onConfirm={() => {
            const { releaseKeys } = confirming;
            setConfirming(null);
            void runAction("stop_wanting", releaseKeys);
          }}
        />
      )}
    </section>
  );
}
