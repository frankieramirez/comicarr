/**
 * Bounded needs-attention preview above the chronological feed (#526).
 *
 * The band **routes, it never works**. It shows at most `preview_cap` group
 * cards in a single row of fixed height and folds the rest into
 * `/activity/attention`. That ceiling is the point: an unbounded `items.map`
 * made the timeline's position on the page depend on how much had gone wrong,
 * and several hundred rows pushed the feed off screen entirely.
 *
 * Red + actions still live only here and on the triage route; stream rows for
 * the same trouble stay muted history with no actions (ADR §2 / #432).
 */

import { Link } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import RelativeTime from "@/components/ui/RelativeTime";
import { stageAccent, stageLabel } from "./attentionStage";
import type { AttentionGroup } from "./types";

/** One card row, so the feed below never moves further than this. */
const CARD_HEIGHT = 104;

function attentionHref(scope_type?: string | null, scope_id?: string | null) {
  const params = new URLSearchParams();
  if (scope_type?.trim() && scope_id?.trim()) {
    params.set("scope_type", scope_type.trim());
    params.set("scope_id", scope_id.trim());
  }
  const qs = params.toString();
  return qs ? `/activity/attention?${qs}` : "/activity/attention";
}

function GroupCard({ group, href }: { group: AttentionGroup; href: string }) {
  const accent = stageAccent(group.stage);

  return (
    <Link
      to={`${href}${href.includes("?") ? "&" : "?"}group=${encodeURIComponent(group.group_key)}`}
      className="flex w-[200px] shrink-0 flex-col rounded-control border bg-[var(--background)] p-2.5 text-left hover:border-[var(--primary)]"
      style={{ borderColor: "var(--border)", height: CARD_HEIGHT }}
    >
      <div className="flex items-center gap-1.5">
        <span
          className="h-1.5 w-1.5 shrink-0 rounded-full"
          style={{ background: accent }}
        />
        <span
          className="font-mono text-[9px] uppercase tracking-wider"
          style={{ color: accent }}
        >
          {stageLabel(group.stage)}
        </span>
        <span className="ml-auto font-mono text-[11px] font-semibold tabular-nums">
          ×{group.member_count}
        </span>
      </div>

      <div className="mt-1.5 line-clamp-2 text-[12px] font-medium leading-snug">
        {group.series_label}
      </div>

      <div className="mt-auto line-clamp-2 text-[10px] text-muted-foreground">
        {group.reason_phrase}
      </div>
    </Link>
  );
}

export function AttentionBand({
  groups,
  total,
  memberTotal,
  previewCap,
  scope_type,
  scope_id,
}: {
  groups: AttentionGroup[];
  total: number;
  memberTotal: number;
  previewCap: number;
  scope_type?: string | null;
  scope_id?: string | null;
}) {
  if (groups.length === 0) return null;

  const href = attentionHref(scope_type, scope_id);
  const preview = groups.slice(0, previewCap);
  const more = total - preview.length;
  const newest = preview[0]?.newest_updated_at;

  return (
    <section
      aria-label="Needs attention"
      className="shrink-0 border-b"
      style={{
        borderColor: "var(--border)",
        background:
          "var(--status-error-bg, color-mix(in oklab, var(--status-error) 8%, transparent))",
      }}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-5 pt-3 pb-2">
        <AlertTriangle
          className="h-3.5 w-3.5"
          style={{ color: "var(--status-error)" }}
        />
        <span
          className="font-mono text-[11px] uppercase tracking-[0.1em]"
          style={{ color: "var(--status-error)" }}
        >
          {total} need{total === 1 ? "s" : ""} attention
        </span>
        <span className="font-mono text-[10px] text-muted-foreground">
          {memberTotal === total
            ? "clears only by action"
            : `${memberTotal} issues · clears only by action`}
        </span>
        {newest && <RelativeTime value={newest} />}
        <Link
          to={href}
          className="ml-auto font-mono text-[11px] hover:underline"
          style={{ color: "var(--status-error)" }}
        >
          See all {total} →
        </Link>
      </div>

      <div className="flex gap-2 overflow-x-auto px-5 pb-3">
        {preview.map((group) => (
          <GroupCard key={group.group_key} group={group} href={href} />
        ))}
        {more > 0 && (
          <Link
            to={href}
            className="flex w-[120px] shrink-0 flex-col items-center justify-center rounded-control border border-dashed font-mono text-[11px] text-muted-foreground hover:text-foreground"
            style={{ borderColor: "var(--border)", height: CARD_HEIGHT }}
          >
            +{more}
            <span className="mt-1">more</span>
          </Link>
        )}
      </div>
    </section>
  );
}
