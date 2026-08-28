/**
 * `/activity/attention` — the needs-attention triage surface (#526).
 *
 * A real route, not a tab and not a sheet: the status bar lands here, deep
 * links survive a refresh, and Timeline · Direct Downloads · Download History
 * keep the tab contract the ADR fixes.
 *
 * **Against Download History:** this shows only *unresolved, actionable*
 * groups and is the only place they can be resolved. History is the full
 * ledger of every outcome and carries no band actions — audit vs work queue.
 */

import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import EmptyState from "@/components/ui/EmptyState";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import FilterField from "@/components/ui/FilterField";
import RelativeTime from "@/components/ui/RelativeTime";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import {
  useActivityBand,
  useBandBatchResolution,
  type BandBatchResult,
} from "@/hooks/useActivity";
import {
  actionLabel,
  stageAccent,
  stageDescription,
  stageLabel,
  type AttentionGroup,
  type AttentionMember,
  type BandAction,
} from "@/components/activity/timeline";
import { StopWantingDialog } from "@/components/activity/attention/StopWantingDialog";

type StageFilter = "all" | "failed" | "manual_review";
type AgeFilter = "all" | "7d" | "30d";

/** A selected row, kept with its group so the bar can count both. */
interface SelectedMember {
  group: AttentionGroup;
  member: AttentionMember;
}

interface StopWantingTarget {
  releaseKeys: string[];
  /** Named in the confirmation when the rows all come from one series. */
  seriesLabel?: string;
}

const AGE_DAYS: Record<Exclude<AgeFilter, "all">, number> = {
  "7d": 7,
  "30d": 30,
};

function withinAge(value: string, age: AgeFilter): boolean {
  if (age === "all") return true;
  const at = Date.parse(value.replace(" ", "T"));
  if (Number.isNaN(at)) return true; // never hide a row because its date is odd
  return Date.now() - at <= AGE_DAYS[age] * 86_400_000;
}

/** Summary toast copy for a multi-status batch (#525) — never a blocking modal. */
function batchSummary(result: BandBatchResult): string {
  const verb = actionLabel(result.action);
  const head =
    result.succeeded === result.processed
      ? `${verb} — ${result.succeeded} ${result.succeeded === 1 ? "issue" : "issues"}.`
      : `${verb} ${result.succeeded} of ${result.processed} — ${result.failed} still ${result.failed === 1 ? "needs" : "need"} attention.`;
  if (!result.capped) return head;
  return `${head} ${result.skipped_for_cap} left for another go (max ${result.cap} at a time).`;
}

export default function AttentionPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const scope_type = searchParams.get("scope_type");
  const scope_id = searchParams.get("scope_id");
  const focusedGroup = searchParams.get("group");

  const [stage, setStage] = useState<StageFilter>("all");
  const [age, setAge] = useState<AgeFilter>("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState<StopWantingTarget | null>(null);

  const band = useActivityBand({ scope_type, scope_id });
  const batch = useBandBatchResolution();
  const { addToast } = useToast();

  const groups = useMemo(() => band.data?.results ?? [], [band.data?.results]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return groups.filter((group) => {
      if (stage !== "all" && group.stage !== stage) return false;
      if (!withinAge(group.newest_updated_at, age)) return false;
      if (!q) return true;
      return (
        group.series_label.toLowerCase().includes(q) ||
        group.reason_phrase.toLowerCase().includes(q)
      );
    });
  }, [groups, stage, age, query]);

  const selectedMembers = useMemo(() => {
    const rows: SelectedMember[] = [];
    for (const group of filtered) {
      for (const member of group.members) {
        if (selected.has(member.release_key)) rows.push({ group, member });
      }
    }
    return rows;
  }, [filtered, selected]);

  const selectedIssues = selectedMembers.length;
  const selectedGroupCount = new Set(
    selectedMembers.map(({ group }) => group.group_key),
  ).size;

  const filteredKeys = useMemo(
    () =>
      filtered.flatMap((group) =>
        group.members.map((member) => member.release_key),
      ),
    [filtered],
  );
  const allSelected =
    filteredKeys.length > 0 && selectedIssues === filteredKeys.length;

  const scoped = Boolean(scope_type?.trim() && scope_id?.trim());

  const clearGroupFocus = () => {
    if (!focusedGroup) return;
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.delete("group");
        return next;
      },
      { replace: true },
    );
  };

  const setKeysSelected = (releaseKeys: string[], picked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const key of releaseKeys) {
        if (picked) next.add(key);
        else next.delete(key);
      }
      return next;
    });
  };

  const runAction = async (action: BandAction, releaseKeys: string[]) => {
    if (releaseKeys.length === 0) return;
    try {
      const result = await batch.mutateAsync({ action, releaseKeys });
      addToast({
        type: result.partial ? "info" : "success",
        message: batchSummary(result),
      });
      setSelected(new Set());
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

  const confirmStopWanting = (releaseKeys: string[], seriesLabel?: string) => {
    if (releaseKeys.length < 2) {
      void runAction("stop_wanting", releaseKeys);
      return;
    }
    setConfirming({ releaseKeys, seriesLabel });
  };

  if (band.isLoading && !band.data) {
    return (
      <div className="page-transition flex h-full min-h-0 flex-col">
        <PageHeader
          title="Needs attention"
          meta="what Comicarr can't finish alone"
        />
        <div className="space-y-2 px-5 py-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      </div>
    );
  }

  if (!band.data && band.error) {
    return (
      <div className="page-transition flex h-full min-h-0 flex-col">
        <PageHeader
          title="Needs attention"
          meta="what Comicarr can't finish alone"
        />
        <div className="px-5 py-4">
          <ErrorDisplay
            error={band.error}
            title="Unable to load needs attention"
            onRetry={() => void band.refetch()}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="page-transition flex h-full min-h-0 flex-col">
      <PageHeader
        title="Needs attention"
        meta={
          groups.length === 0
            ? "nothing is waiting on you"
            : `${groups.length} ${groups.length === 1 ? "problem" : "problems"} · ${band.data?.member_total ?? 0} issues`
        }
        actions={
          <Link
            to="/activity"
            className="inline-flex items-center gap-1 rounded-[5px] border px-2 py-1 font-mono text-[11px] text-muted-foreground hover:text-foreground"
            style={{ borderColor: "var(--border)" }}
          >
            <ArrowLeft className="h-3 w-3" /> Activity
          </Link>
        }
      />

      {scoped && (
        <div className="flex shrink-0 items-center gap-2 border-b border-border px-5 py-2 font-mono text-[11px] text-muted-foreground">
          <span>
            Scoped to {scope_type}:{scope_id}
          </span>
          <Link
            to="/activity/attention"
            className="ml-auto hover:text-foreground"
          >
            clear scope
          </Link>
        </div>
      )}

      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-5 py-2.5">
        <div className="max-w-xs flex-1">
          <FilterField
            placeholder="Filter by series or reason…"
            aria-label="Filter needs attention"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            shortcut="/"
          />
        </div>
        <div
          role="group"
          aria-label="Filter by stage"
          className="flex items-center gap-1"
        >
          {(
            [
              ["all", "All"],
              ["failed", "Failed"],
              ["manual_review", "Manual review"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-pressed={stage === id}
              onClick={() => setStage(id)}
              className="rounded-[4px] border px-2 py-1 font-mono text-[10px] text-muted-foreground hover:text-foreground"
              style={{
                borderColor: "var(--border)",
                background:
                  stage === id
                    ? "color-mix(in oklab, var(--primary) 12%, transparent)"
                    : undefined,
                color: stage === id ? "var(--foreground)" : undefined,
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <select
          aria-label="Filter by age"
          value={age}
          onChange={(e) => setAge(e.target.value as AgeFilter)}
          className="rounded-[5px] border bg-transparent px-2 py-1.5 font-mono text-[11px] text-muted-foreground"
          style={{ borderColor: "var(--border)" }}
        >
          <option value="all">any age</option>
          <option value="7d">last 7 days</option>
          <option value="30d">last 30 days</option>
        </select>
        {filteredKeys.length > 0 && (
          <label className="flex cursor-pointer items-center gap-1.5 font-mono text-[10px] text-muted-foreground hover:text-foreground">
            <input
              type="checkbox"
              checked={allSelected}
              ref={(node) => {
                if (node)
                  node.indeterminate = selectedIssues > 0 && !allSelected;
              }}
              onChange={() => setKeysSelected(filteredKeys, !allSelected)}
              aria-label={`Select all ${filteredKeys.length} issues`}
            />
            select all {filteredKeys.length}
          </label>
        )}
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">
          unresolved only · Download History keeps the full ledger
        </span>
      </div>

      {selectedIssues > 0 && (
        <div
          role="group"
          aria-label="Selected issues"
          className="flex shrink-0 flex-wrap items-center gap-2 border-b px-5 py-2"
          style={{
            borderColor: "var(--border)",
            background: "color-mix(in oklab, var(--primary) 8%, transparent)",
          }}
        >
          <span className="font-mono text-[11px]">
            {selectedGroupCount}{" "}
            {selectedGroupCount === 1 ? "problem" : "problems"} ·{" "}
            {selectedIssues} {selectedIssues === 1 ? "issue" : "issues"}
          </span>
          {selectedIssues > 25 && (
            <span
              className="font-mono text-[10px]"
              style={{ color: "var(--status-paused)" }}
            >
              25 at a time — the rest stay here
            </span>
          )}
          {sharedActions(selectedMembers).length === 0 ? (
            <span className="font-mono text-[10px] text-muted-foreground">
              these rows are at different stages — no action fits all of them
            </span>
          ) : (
            sharedActions(selectedMembers).map((action) => (
              <button
                key={action}
                type="button"
                disabled={batch.isPending}
                onClick={() => {
                  const keys = selectedMembers.map(
                    ({ member }) => member.release_key,
                  );
                  if (action === "stop_wanting") {
                    confirmStopWanting(
                      keys,
                      selectedGroupCount === 1
                        ? selectedMembers[0].group.series_label
                        : undefined,
                    );
                  } else {
                    void runAction(action, keys);
                  }
                }}
                className="rounded-[4px] border px-2 py-1 font-mono text-[10px] text-muted-foreground hover:text-foreground disabled:opacity-60"
                style={{ borderColor: "var(--border)" }}
              >
                {actionLabel(action)}
                {action === "stop_wanting" ? "…" : ""}
              </button>
            ))
          )}
          <button
            type="button"
            onClick={() => setSelected(new Set())}
            className="ml-auto font-mono text-[10px] text-muted-foreground hover:text-foreground"
          >
            clear selection
          </button>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-auto p-5">
        {filtered.length === 0 ? (
          <EmptyState
            variant="custom"
            eyebrow={
              groups.length === 0 ? "ATTENTION · CLEAR" : "ATTENTION · FILTERED"
            }
            title={
              groups.length === 0
                ? "Nothing needs your attention"
                : "Nothing matches these filters"
            }
            description={
              groups.length === 0
                ? "Failures and stalled imports show up here until you act on them. Finished work lives in Download History."
                : "Try a wider stage or age filter."
            }
            action={
              groups.length === 0
                ? { label: "Back to Activity", to: "/activity" }
                : undefined
            }
          />
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {filtered.map((group) => (
              <GroupPanel
                key={group.group_key}
                group={group}
                selectedKeys={selected}
                focused={group.group_key === focusedGroup}
                busy={batch.isPending}
                onSelect={setKeysSelected}
                onFocusSeen={clearGroupFocus}
                onAction={(action, releaseKeys) =>
                  action === "stop_wanting"
                    ? confirmStopWanting(releaseKeys, group.series_label)
                    : void runAction(action, releaseKeys)
                }
              />
            ))}
          </ul>
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
    </div>
  );
}

/**
 * Actions every selected *row* allows. Intersecting members rather than groups
 * is what lets a selection spanning two stages still offer whatever both admit
 * — and say so plainly when nothing does.
 */
function sharedActions(rows: SelectedMember[]): BandAction[] {
  if (rows.length === 0) return [];
  return rows
    .map(({ member }) => member.available_actions)
    .reduce((shared: BandAction[], actions: BandAction[]) =>
      shared.filter((action) => actions.includes(action)),
    );
}

function GroupPanel({
  group,
  selectedKeys,
  focused,
  busy,
  onSelect,
  onFocusSeen,
  onAction,
}: {
  group: AttentionGroup;
  selectedKeys: Set<string>;
  focused: boolean;
  busy: boolean;
  onSelect: (releaseKeys: string[], picked: boolean) => void;
  onFocusSeen: () => void;
  onAction: (action: BandAction, releaseKeys: string[]) => void;
}) {
  const memberKeys = group.members.map((member) => member.release_key);
  const pickedCount = memberKeys.filter((key) => selectedKeys.has(key)).length;
  const allPicked = pickedCount === memberKeys.length && pickedCount > 0;
  const mixedStages = group.available_actions.length === 0;

  const [override, setOverride] = useState<boolean | null>(null);
  const expanded = override ?? (focused || mixedStages);
  const accent = stageAccent(group.stage);

  return (
    <li
      className="rounded-[5px] border p-3"
      style={{
        borderColor: focused ? accent : "var(--border)",
        background: focused
          ? "color-mix(in oklab, var(--primary) 5%, transparent)"
          : undefined,
      }}
    >
      <div className="flex items-start gap-2">
        <input
          type="checkbox"
          className="mt-1"
          checked={allPicked}
          ref={(node) => {
            if (node) node.indeterminate = pickedCount > 0 && !allPicked;
          }}
          onChange={() => onSelect(memberKeys, !allPicked)}
          aria-label={`Select all ${group.member_count} in ${group.series_label}`}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className="font-mono text-[9px] uppercase tracking-wider"
              style={{ color: accent }}
              title={stageDescription(group.stage)}
            >
              {stageLabel(group.stage)}
            </span>
            <RelativeTime value={group.newest_updated_at} />
            <span className="ml-auto font-mono text-[12px] tabular-nums">
              ×{group.member_count}
            </span>
          </div>

          <div className="mt-1 text-[13px] font-medium leading-snug">
            {group.comicid ? (
              <Link
                to={`/library/${group.comicid}`}
                className="hover:text-[var(--primary)]"
              >
                {group.series_label}
              </Link>
            ) : (
              group.series_label
            )}
          </div>

          <div className="mt-1 text-[12px] text-muted-foreground">
            {group.reason_phrase}
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {mixedStages ? (
              <span className="font-mono text-[10px] text-muted-foreground">
                these issues stopped at different stages — pick the ones you
                mean
              </span>
            ) : (
              group.available_actions.map((action) => (
                <button
                  key={action}
                  type="button"
                  disabled={busy}
                  onClick={() => onAction(action, memberKeys)}
                  className="rounded-[4px] border px-2 py-1 font-mono text-[10px] text-muted-foreground hover:text-foreground disabled:opacity-60"
                  style={{ borderColor: "var(--border)" }}
                >
                  {actionLabel(action)}
                  {action === "stop_wanting" && group.member_count > 1
                    ? "…"
                    : ""}
                </button>
              ))
            )}
            {group.member_count > 1 && (
              <button
                type="button"
                onClick={() => {
                  setOverride(!expanded);
                  if (focused) onFocusSeen();
                }}
                aria-expanded={expanded}
                className="ml-auto font-mono text-[10px] text-muted-foreground hover:text-foreground"
              >
                {expanded ? "hide issues" : `show ${group.member_count} issues`}
              </button>
            )}
          </div>

          {expanded && (
            <ul
              className="mt-2 space-y-1 border-t pt-2"
              style={{ borderColor: "var(--border)" }}
            >
              {group.members.map((member) => (
                <li
                  key={member.release_key}
                  className="flex items-center gap-2 text-[11px] text-muted-foreground"
                >
                  <input
                    type="checkbox"
                    checked={selectedKeys.has(member.release_key)}
                    onChange={(e) =>
                      onSelect([member.release_key], e.target.checked)
                    }
                    aria-label={`Select ${member.issue_label}`}
                  />
                  <span className="truncate">{member.issue_label}</span>
                  {/* Only worth naming when the group can't speak for it. */}
                  {mixedStages && (
                    <span
                      className="shrink-0 font-mono text-[9px] uppercase"
                      style={{ color: stageAccent(member.stage) }}
                      title={stageDescription(member.stage)}
                    >
                      {stageLabel(member.stage)}
                    </span>
                  )}
                  <span className="ml-auto shrink-0">
                    <RelativeTime value={member.updated_date} />
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </li>
  );
}
