import { useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import {
  actionLabel,
  stageAccent,
  type AttentionGroup,
  type BandAction,
} from "@/components/activity/timeline";
import { StopWantingDialog } from "@/components/activity/attention/StopWantingDialog";
import { PanelUnavailable } from "@/components/dashboard/DashboardPanel";
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

function GroupRow({
  group,
  busy,
  onAction,
}: {
  group: AttentionGroup;
  busy: boolean;
  onAction: (action: BandAction, group: AttentionGroup) => void;
}) {
  const accent = stageAccent(group.stage);
  const mixed = group.available_actions.length === 0;
  const triageGroupHref = `${TRIAGE_HREF}?group=${encodeURIComponent(
    group.group_key,
  )}`;

  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-1.5"
      data-testid="needs-attention-group"
    >
      <span
        className="h-1.5 w-1.5 shrink-0 rounded-full"
        style={{ background: accent }}
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1 font-mono text-[11px]">
        {group.comicid ? (
          <Link
            to={`/library/${group.comicid}`}
            className="text-foreground hover:text-[var(--primary)]"
          >
            {group.series_label}
          </Link>
        ) : (
          <span className="text-foreground">{group.series_label}</span>
        )}
        {group.member_count > 1 && (
          <span className="text-muted-foreground"> ×{group.member_count}</span>
        )}
        <span className="text-muted-foreground"> — {group.reason_phrase}</span>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {mixed ? (
          <Link
            to={triageGroupHref}
            className="font-mono text-[10px] text-muted-foreground hover:text-foreground"
          >
            open triage →
          </Link>
        ) : (
          group.available_actions.map((action) => (
            <button
              key={action}
              type="button"
              disabled={busy}
              onClick={() => onAction(action, group)}
              className="rounded-[4px] border px-2 py-1 font-mono text-[10px] text-muted-foreground hover:text-foreground disabled:opacity-60"
              style={{ borderColor: "var(--border)" }}
            >
              {actionLabel(action)}
              {action === "stop_wanting" && group.member_count > 1 ? "…" : ""}
            </button>
          ))
        )}
      </div>
    </div>
  );
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

  const onGroupAction = (action: BandAction, group: AttentionGroup) => {
    const releaseKeys = group.members.map((member) => member.release_key);
    if (action === "stop_wanting" && releaseKeys.length >= 2) {
      setConfirming({ releaseKeys, seriesLabel: group.series_label });
      return;
    }
    void runAction(action, releaseKeys);
  };

  if (band.isPending) {
    return (
      <div className="px-5 py-2.5" data-testid="needs-attention-loading">
        <div
          aria-hidden="true"
          className="h-2.5 w-48 animate-pulse rounded-[2px] bg-primary/10"
        />
      </div>
    );
  }

  if (band.isError) {
    return (
      <div className="px-5">
        <PanelUnavailable
          label="Needs attention"
          onRetry={() => void band.refetch()}
          isRetrying={band.isFetching}
        />
      </div>
    );
  }

  const groups = band.data?.results ?? [];
  const total = band.data?.total ?? groups.length;
  const previewCap = band.data?.preview_cap ?? 5;
  const preview = groups.slice(0, previewCap);
  const more = Math.max(0, total - preview.length);

  if (total === 0) {
    return (
      <div className="px-5 py-2.5" data-testid="needs-attention-empty">
        <span className="font-mono text-[11px] text-muted-foreground">
          Nothing needs you
        </span>
      </div>
    );
  }

  return (
    <section
      aria-label="Needs attention"
      style={{
        background:
          "var(--status-error-bg, color-mix(in oklab, var(--status-error) 8%, transparent))",
      }}
      data-testid="needs-attention-band"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-5 pt-3 pb-1.5">
        <AlertTriangle
          className="h-3.5 w-3.5"
          style={{ color: "var(--status-error)" }}
          aria-hidden="true"
        />
        <span
          className="font-mono text-[11px] uppercase tracking-[0.1em]"
          style={{ color: "var(--status-error)" }}
        >
          {total} need{total === 1 ? "s" : ""} attention
        </span>
        <Link
          to={TRIAGE_HREF}
          className="ml-auto font-mono text-[11px] hover:underline"
          style={{ color: "var(--status-error)" }}
        >
          See all {total} →
        </Link>
      </div>

      <div className="px-5 pb-3">
        {preview.map((group) => (
          <GroupRow
            key={group.group_key}
            group={group}
            busy={batch.isPending}
            onAction={onGroupAction}
          />
        ))}
        {more > 0 && (
          <Link
            to={TRIAGE_HREF}
            className="mt-1 inline-block font-mono text-[11px] text-muted-foreground hover:text-foreground"
            data-testid="needs-attention-more"
          >
            +{more} more…
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
