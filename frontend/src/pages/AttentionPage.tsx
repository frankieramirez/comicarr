import { ph, plural, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
/**
 * `/activity/attention` — the needs-attention triage surface (#526).
 *
 * A real route, not a tab and not a sheet: the status bar lands here, deep
 * links survive a refresh, and Timeline · Direct downloads · History
 * keep the tab contract the ADR fixes.
 *
 * **Against Download History:** this shows only *unresolved, actionable*
 * groups and is the only place they can be resolved. History is the full
 * ledger of every outcome and carries no band actions — audit vs work queue.
 */

import { SEGMENTED_GROUP, SEGMENTED_ITEM } from "@/lib/segmented";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import PageHeader from "@/components/layout/PageHeader";
import { ActivityTabs } from "@/components/activity/ActivityTabs";
import PageShell from "@/components/layout/PageShell";
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
import { ImportManuallyDialog } from "@/components/activity/attention/ImportManuallyDialog";
import { SystemProblemList } from "@/components/activity/attention/SystemProblems";
import { useSystemProblems } from "@/hooks/useSystemProblems";

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
  const succeeded = result.succeeded;
  const processed = result.processed;
  const head =
    succeeded === processed
      ? plural(succeeded, {
          one: `${verb} — # issue.`,
          other: `${verb} — # issues.`,
        })
      : plural(result.failed, {
          one: `${verb} ${succeeded} of ${processed} — # still needs attention.`,
          other: `${verb} ${succeeded} of ${processed} — # still need attention.`,
        });
  if (!result.capped) return head;
  return t`${head} ${ph({ skipped_for_cap: result.skipped_for_cap })} left for another go (max ${ph({ cap: result.cap })} at a time).`;
}

/** "2 problems · 5 issues". */
function problemsSummary(problems: number, issues: number): string {
  const problemCount = plural(problems, {
    one: "# problem",
    other: "# problems",
  });
  const issueCount = plural(issues, { one: "# issue", other: "# issues" });
  return t`${problemCount} · ${issueCount}`;
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
  const [importing, setImporting] = useState<{
    releaseKey: string;
    label?: string;
  } | null>(null);

  const band = useActivityBand({ scope_type, scope_id });
  const systemProblems = useSystemProblems();
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
  // Library-wide problems have no series or stage, so a scope or the
  // Manual review filter leaves them out.
  const showSystem =
    !scoped && stage !== "manual_review" && systemProblems.count > 0;

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
            : t`Unable to apply “${ph({ action: actionLabel(action) })}” to these issues.`,
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
      <PageShell
        header={
          <>
            <PageHeader
              title={t`Activity`}
              meta={t`What Comicarr can't finish without you`}
            />
            <ActivityTabs active="attention" />
          </>
        }
      >
        <div className="space-y-2 px-8 py-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      </PageShell>
    );
  }

  if (!band.data && band.error) {
    return (
      <PageShell
        header={
          <>
            <PageHeader
              title={t`Activity`}
              meta={t`What Comicarr can't finish without you`}
            />
            <ActivityTabs active="attention" />
          </>
        }
      >
        <div className="px-8 py-4">
          <ErrorDisplay
            error={band.error}
            title={t`Unable to load needs attention`}
            onRetry={() => void band.refetch()}
          />
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell
      header={
        <>
          <PageHeader
            title={t`Activity`}
            meta={
              groups.length > 0
                ? problemsSummary(groups.length, band.data?.member_total ?? 0)
                : showSystem
                  ? plural(systemProblems.count, {
                      one: "# problem stops work for the whole library",
                      other: "# problems stop work for the whole library",
                    })
                  : t`Nothing is waiting on you`
            }
          />
          <ActivityTabs active="attention" />

          {scoped && (
            <div className="flex shrink-0 items-center gap-2 border-b border-border px-8 py-2 mono-meta">
              <span>
                <Trans>
                  Scoped to {scope_type}:{scope_id}
                </Trans>
              </span>
              <Link
                to="/activity/attention"
                className="ms-auto hover:text-foreground"
              >
                <Trans>clear scope</Trans>
              </Link>
            </div>
          )}

          <div className="flex shrink-0 flex-wrap items-center gap-2 px-8 pt-1 pb-3">
            <div className="max-w-xs flex-1">
              <FilterField
                placeholder={t`Filter by series or reason…`}
                aria-label={t`Filter needs attention`}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                shortcut="/"
              />
            </div>
            <div
              role="group"
              aria-label={t`Filter by stage`}
              className={SEGMENTED_GROUP}
            >
              {(
                [
                  ["all", t`All`],
                  ["failed", t`Failed`],
                  ["manual_review", t`Manual review`],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  aria-pressed={stage === id}
                  onClick={() => setStage(id)}
                  className={SEGMENTED_ITEM}
                >
                  {label}
                </button>
              ))}
            </div>
            <select
              aria-label={t`Filter by age`}
              value={age}
              onChange={(e) => setAge(e.target.value as AgeFilter)}
              className="rounded-control border bg-transparent px-2 py-1.5 mono-meta"
              style={{ borderColor: "var(--border)" }}
            >
              <option value="all">
                <Trans>any age</Trans>
              </option>
              <option value="7d">
                <Trans>last 7 days</Trans>
              </option>
              <option value="30d">
                <Trans>last 30 days</Trans>
              </option>
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
                  aria-label={plural(filteredKeys.length, {
                    one: "Select all # issue",
                    other: "Select all # issues",
                  })}
                />
                {t`select all ${ph({ count: filteredKeys.length })}`}
              </label>
            )}
            <span className="ms-auto font-mono text-[10px] text-muted-foreground">
              <Trans>unresolved only · History keeps the full ledger</Trans>
            </span>
          </div>

          {selectedIssues > 0 && (
            <div
              role="group"
              aria-label={t`Selected issues`}
              className="flex shrink-0 flex-wrap items-center gap-2 border-b px-8 py-2"
              style={{
                borderColor: "var(--border)",
                background:
                  "color-mix(in oklab, var(--primary) 8%, transparent)",
              }}
            >
              <span className="font-mono text-[11px]">
                {problemsSummary(selectedGroupCount, selectedIssues)}
              </span>
              {selectedIssues > 25 && (
                <span
                  className="font-mono text-[10px]"
                  style={{ color: "var(--status-paused)" }}
                >
                  <Trans>25 at a time — the rest stay here</Trans>
                </span>
              )}
              {sharedActions(selectedMembers).length === 0 ? (
                <span className="font-mono text-[10px] text-muted-foreground">
                  <Trans>
                    these rows are at different stages — no action fits all of
                    them
                  </Trans>
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
                    className="rounded-md border px-2 py-1 font-mono text-[10px] text-muted-foreground hover:text-foreground disabled:opacity-60"
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
                className="ms-auto font-mono text-[10px] text-muted-foreground hover:text-foreground"
              >
                <Trans>clear selection</Trans>
              </button>
            </div>
          )}
        </>
      }
    >
      <div className="px-8 pb-6 pt-1">
        {showSystem && <SystemProblemList problems={systemProblems} />}
        {filtered.length === 0 &&
        showSystem &&
        groups.length === 0 ? null : filtered.length === 0 ? (
          <EmptyState
            variant="custom"
            eyebrow={
              groups.length === 0
                ? t`ATTENTION · CLEAR`
                : t`ATTENTION · FILTERED`
            }
            title={
              groups.length === 0
                ? t`Nothing needs your attention`
                : t`Nothing matches these filters`
            }
            description={
              groups.length === 0
                ? t`Failures and stalled imports show up here until you act on them. Finished work lives in History.`
                : t`Try a wider stage or age filter.`
            }
            action={
              groups.length === 0
                ? { label: t`Back to Activity`, to: "/activity" }
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
                    : action === "import" && releaseKeys.length === 1
                      ? setImporting({
                          releaseKey: releaseKeys[0],
                          label: group.members?.[0]?.issue_label,
                        })
                      : void runAction(action, releaseKeys)
                }
              />
            ))}
          </ul>
        )}
      </div>

      {importing && (
        <ImportManuallyDialog
          releaseKey={importing.releaseKey}
          label={importing.label}
          onClose={() => setImporting(null)}
        />
      )}

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
    </PageShell>
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
      className="rounded-control border p-3"
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
          aria-label={t`Select all ${ph({ member_count: group.member_count })} in ${ph({ series_label: group.series_label })}`}
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
            <span className="ms-auto font-mono text-[12px] tabular-nums">
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
                <Trans>
                  these issues stopped at different stages — pick the ones you
                  mean
                </Trans>
              </span>
            ) : (
              group.available_actions.map((action) => (
                <button
                  key={action}
                  type="button"
                  disabled={busy}
                  onClick={() => onAction(action, memberKeys)}
                  className="rounded-md border px-2 py-1 font-mono text-[10px] text-muted-foreground hover:text-foreground disabled:opacity-60"
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
                className="ms-auto font-mono text-[10px] text-muted-foreground hover:text-foreground"
              >
                {expanded
                  ? t`hide issues`
                  : plural(group.member_count, {
                      one: "show # issue",
                      other: "show # issues",
                    })}
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
                    aria-label={t`Select ${ph({ issue_label: member.issue_label })}`}
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
                  <span className="ms-auto shrink-0">
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
