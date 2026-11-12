import { useState } from "react";
import { Link } from "react-router-dom";
import { MoreHorizontal } from "lucide-react";
import {
  actionLabel,
  stageAccent,
  type AttentionGroup,
  type BandAction,
} from "@/components/activity/timeline";
import { StopWantingDialog } from "@/components/activity/attention/StopWantingDialog";
import {
  PanelUnavailable,
  SectionHeader,
} from "@/components/dashboard/DashboardPanel";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
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

function GroupRow({
  group,
  busy,
  primaryRow,
  onAction,
}: {
  group: AttentionGroup;
  busy: boolean;
  /** The first row carries the view's one filled button. */
  primaryRow: boolean;
  onAction: (action: BandAction, group: AttentionGroup) => void;
}) {
  const accent = stageAccent(group.stage);
  const mixed = group.available_actions.length === 0;
  const triageGroupHref = `${TRIAGE_HREF}?group=${encodeURIComponent(
    group.group_key,
  )}`;
  const [primary, ...rest] = group.available_actions;
  const actionText = (action: BandAction) =>
    `${actionLabel(action)}${
      action === "stop_wanting" && group.member_count > 1 ? "…" : ""
    }`;
  const issues = `${group.member_count} ${
    group.member_count === 1 ? "issue" : "issues"
  }`;

  return (
    <div
      className="flex items-center gap-3 border-b border-border-subtle py-2.5"
      data-testid="needs-attention-group"
    >
      <span
        className="size-1.5 shrink-0 rounded-full"
        style={{ background: accent }}
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-foreground">
          {group.comicid ? (
            <Link
              to={`/library/${group.comicid}`}
              className="hover:underline underline-offset-2"
            >
              {group.series_label}
            </Link>
          ) : (
            <span>{group.series_label}</span>
          )}
        </div>
        <div className="truncate text-[13px] text-foreground-2">
          <span className="first-letter:uppercase">{group.reason_phrase}</span>
          {group.member_count > 1 && <span> · {issues}</span>}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-1">
        {mixed ? (
          <Link
            to={triageGroupHref}
            className="inline-flex h-8 items-center rounded-control border border-border-strong bg-surface-2 px-3 text-[13px] font-medium hover:bg-surface-3"
          >
            Open triage
          </Link>
        ) : (
          <>
            <Button
              type="button"
              variant={primaryRow ? "default" : "outline"}
              size="toolbar"
              className={primaryRow ? "" : "bg-surface-2"}
              disabled={busy}
              onClick={() => onAction(primary, group)}
            >
              {actionText(primary)}
            </Button>
            {rest.length > 0 && (
              <DropdownMenu>
                <DropdownMenuTrigger
                  render={
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      disabled={busy}
                      aria-label={`More actions for ${group.series_label}`}
                    >
                      <MoreHorizontal />
                    </Button>
                  }
                />
                <DropdownMenuContent align="end">
                  {rest.map((action) => (
                    <DropdownMenuItem
                      key={action}
                      onClick={() => onAction(action, group)}
                    >
                      {actionText(action)}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </>
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

  const groups = band.data?.results ?? [];
  const total = band.data?.total ?? groups.length;
  const memberTotal = band.data?.member_total;
  const previewCap = band.data?.preview_cap ?? 5;
  const preview = groups.slice(0, previewCap);
  const more = Math.max(0, total - preview.length);

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
        meta={
          <>
            <span>
              {total} need{total === 1 ? "s" : ""} attention
            </span>
            {memberTotal != null && memberTotal > total && (
              <> · {memberTotal} issues</>
            )}
          </>
        }
        action={{ label: `See all ${total}`, to: TRIAGE_HREF }}
      />

      <div className="border-t border-border-subtle">
        {preview.map((group, index) => (
          <GroupRow
            key={group.group_key}
            group={group}
            primaryRow={index === 0}
            busy={batch.isPending}
            onAction={onGroupAction}
          />
        ))}
        {more > 0 && (
          <Link
            to={TRIAGE_HREF}
            className="block py-2.5 pl-[18px] text-[13px] text-foreground-2 hover:text-foreground"
            data-testid="needs-attention-more"
          >
            +{more} more in other series
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
