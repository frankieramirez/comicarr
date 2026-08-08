import { useState, type ReactNode, type SubmitEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowUp, RefreshCw } from "lucide-react";
import {
  PanelBody,
  PanelSkeleton,
  PanelUnavailable,
} from "@/components/dashboard/DashboardPanel";
import HealthBand from "@/components/dashboard/HealthBand";
import InFlightLine from "@/components/dashboard/InFlightLine";
import { panelState, type PanelState } from "@/lib/panelState";
import { Kbd } from "@/components/ui/kbd";
import RelativeTime from "@/components/ui/RelativeTime";
import { useToast } from "@/components/ui/toast";
import {
  useDashboardActivity,
  useDashboardLibrary,
  useDashboardScanTargets,
  useDashboardUpcoming,
} from "@/hooks/useDashboard";
import { useChatThreads } from "@/hooks/useLibraryChat";
import {
  useComicScan,
  useComicScanProgress,
  useMangaScan,
  useMangaScanProgress,
} from "@/hooks/useImport";

function Kpi({
  label,
  value,
  state,
  onRetry,
  borderLeft,
}: {
  label: string;
  value: string;
  state: PanelState;
  onRetry: () => void;
  borderLeft?: boolean;
}) {
  return (
    <div className={`px-5 py-4 ${borderLeft ? "border-l border-border" : ""}`}>
      <div className="mono-label">{label}</div>
      <div className="flex items-end gap-2 mt-1.5 h-[26px]">
        {state === "loading" ? (
          <div
            aria-hidden="true"
            className="h-4 w-16 self-center animate-pulse rounded-[2px] bg-primary/10"
          />
        ) : state === "unavailable" ? (
          <div className="flex items-center gap-2 self-center font-mono text-[11px]">
            <span style={{ color: "var(--status-error)" }}>unavailable</span>
            <button
              type="button"
              onClick={onRetry}
              aria-label={`Retry ${label}`}
              className="text-muted-foreground hover:text-foreground"
            >
              <RefreshCw className="w-3 h-3" />
            </button>
          </div>
        ) : (
          <div className="text-[26px] font-semibold tracking-tight leading-none">
            {value}
          </div>
        )}
      </div>
    </div>
  );
}

/** Panel heading plus its count and a link out to the full view. */
function PanelHeader({
  title,
  meta,
  action,
}: {
  title: string;
  meta: ReactNode;
  action?: { label: string; to: string };
}) {
  return (
    <div className="flex items-center justify-between gap-3 mb-3">
      <div className="flex items-center gap-2.5">
        <div className="text-[13px] font-semibold">{title}</div>
        <div className="font-mono text-[10px] text-muted-foreground tracking-wider uppercase">
          {meta}
        </div>
      </div>
      {action && (
        <Link
          to={action.to}
          className="font-mono text-[10px] text-muted-foreground hover:text-foreground"
        >
          {action.label}
        </Link>
      )}
    </div>
  );
}

/** A count that refuses to claim zero for a source that never answered. */
function countMeta(state: PanelState, count: number, noun: string): string {
  if (state === "loading") return "…";
  if (state === "unavailable") return "unavailable";
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/** The header's version of the same rule: a fact only once a panel has one. */
function summarize(state: PanelState, source: string, fact: string): string {
  if (state === "loading") return "loading…";
  if (state === "unavailable") return `${source} unavailable`;
  return fact;
}

const ASK_SUGGESTIONS = [
  "Which runs have gaps?",
  "What landed this week?",
  "Anything stuck in the queue?",
];

export default function DashboardPage() {
  const library = useDashboardLibrary();
  const activity = useDashboardActivity();
  const upcoming = useDashboardUpcoming();
  const scanTargets = useDashboardScanTargets();
  const navigate = useNavigate();
  const chatThreadsQuery = useChatThreads();
  const [question, setQuestion] = useState("");

  const recentChats = (
    chatThreadsQuery.data?.pages.flatMap((page) => page.threads) || []
  ).slice(0, 3);

  /** Hand the question to the chat workspace, which asks it on arrival. */
  const handleAsk = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed) return;
    setQuestion("");
    navigate(`/chat?q=${encodeURIComponent(trimmed)}`);
  };
  const comicScan = useComicScan();
  const mangaScan = useMangaScan();
  const { data: comicScanProgress } = useComicScanProgress();
  const { data: mangaScanProgress } = useMangaScanProgress();
  const { addToast } = useToast();

  const stats = library.data?.stats;
  const activityEvents = activity.data?.events ?? [];
  const activityDays = activity.data?.days ?? 30;
  const upcomingReleases = upcoming.data?.releases ?? [];

  const activeSeries = stats?.total_series ?? 0;
  const totalIssues = stats?.total_issues ?? 0;
  const completion = stats?.completion_pct ?? 0;

  const libraryState = panelState(library, false);
  const activityState = panelState(activity, activityEvents.length === 0);
  const upcomingState = panelState(upcoming, upcomingReleases.length === 0);
  const chatsState = panelState(chatThreadsQuery, recentChats.length === 0);

  const comicScanning = comicScanProgress?.status === "scanning";
  const mangaScanning = mangaScanProgress?.status === "scanning";
  const scanPending =
    comicScan.isPending ||
    mangaScan.isPending ||
    comicScanning ||
    mangaScanning;
  // A failed read is not a library that was never configured. The button only
  // renders once the read succeeded, so "Configure a library directory first"
  // can never end up naming the wrong cause; a failed read says so instead.
  const canScan = Boolean(scanTargets.data?.comic || scanTargets.data?.manga);
  const scanTitle = canScan
    ? "Scan configured comic and manga libraries"
    : "Configure a library directory first";

  // The summary repeats each panel's own verdict rather than re-deriving it,
  // so a broken source says so instead of contributing a zero that reads as
  // fact. `panelState` stays the only place the precedence lives. Open work is
  // absent here on purpose: `InFlightLine` is the only place that reports it.
  const summary = summarize(
    libraryState,
    "library",
    `${activeSeries} series · ${totalIssues} issues`,
  );

  const handleLibraryScan = async () => {
    const scanRequests: Promise<unknown>[] = [];
    if (scanTargets.data?.comic) {
      scanRequests.push(comicScan.mutateAsync());
    }
    if (scanTargets.data?.manga) {
      scanRequests.push(mangaScan.mutateAsync());
    }

    if (scanRequests.length === 0) {
      addToast({
        type: "error",
        message:
          "Configure a comic or manga library directory before scanning.",
      });
      return;
    }

    const results = await Promise.allSettled(scanRequests);
    const started = results.filter(
      (result) => result.status === "fulfilled",
    ).length;
    if (started === scanRequests.length) {
      addToast({
        type: "success",
        message: `${started === 2 ? "Comic and manga library scans" : "Library scan"} started.`,
      });
    } else if (started > 0) {
      addToast({
        type: "error",
        message: "One library scan started, but another failed to start.",
      });
    } else {
      addToast({ type: "error", message: "Failed to start library scans." });
      return;
    }

    navigate("/import");
  };

  return (
    <div className="h-full flex flex-col page-transition">
      {/* Page header */}
      <div className="px-5 py-4 border-b border-border flex items-center justify-between gap-3">
        <div>
          <div className="text-[18px] font-semibold tracking-tight">
            Dashboard
          </div>
          <div className="font-mono text-[11px] text-muted-foreground mt-0.5">
            {summary}
          </div>
        </div>
        {scanTargets.isError ? (
          <PanelUnavailable
            label="Scan targets"
            onRetry={() => void scanTargets.refetch()}
            isRetrying={scanTargets.isFetching}
          />
        ) : (
          <button
            type="button"
            onClick={() => void handleLibraryScan()}
            disabled={!canScan || scanPending}
            title={scanTitle}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[5px] border text-[12px] font-medium disabled:opacity-50"
            style={{ borderColor: "var(--border)" }}
          >
            <RefreshCw
              className={`w-3.5 h-3.5 ${scanPending ? "animate-spin" : ""}`}
            />
            {scanPending ? "Scanning…" : "Scan libraries"}
          </button>
        )}
      </div>

      {/* Health band — above every other panel, because it is the only one
          whose answer can require action today (dashboard-spec.md §2, §3.1). */}
      <HealthBand />

      {/* How much work is moving, across every route (dashboard-spec.md §3.3) */}
      <InFlightLine />

      {/* Ask bar — a question here opens as a chat instead of a search */}
      <div className="px-5 py-3.5 border-b border-border bg-card/30 flex flex-col gap-2.5">
        <form
          onSubmit={handleAsk}
          className="flex items-center gap-2.5 px-3 py-2.5 rounded-[10px] border border-border bg-card focus-within:border-primary"
        >
          <span className="flex size-4.5 shrink-0 items-center justify-center rounded-[5px] bg-primary/15">
            <span className="size-[5px] rounded-[1px] bg-primary" />
          </span>
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            aria-label="Ask about your library"
            placeholder="Ask about your library — gaps, publishers, what to read next…"
            className="min-w-0 flex-1 bg-transparent text-[14px] outline-none placeholder:text-muted-foreground"
          />
          <Kbd className="hidden sm:inline-flex">⌘⇧K</Kbd>
          <button
            type="submit"
            aria-label="Ask Comicarr"
            disabled={!question.trim()}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[7px] bg-primary text-primary-foreground disabled:opacity-40"
          >
            <ArrowUp className="w-3.5 h-3.5" />
          </button>
        </form>
        <div className="flex flex-wrap gap-1.5">
          {ASK_SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => setQuestion(suggestion)}
              className="h-[26px] px-2.5 rounded-full border border-border text-[12px] text-muted-foreground hover:text-foreground hover:border-ring"
            >
              {suggestion}
            </button>
          ))}
        </div>
      </div>

      {/* Everything below the ask bar scrolls inside the page column. */}
      <div className="flex-1 min-h-0 overflow-auto">
        {/* KPI strip — the library, and only the library */}
        <div className="grid grid-cols-2 lg:grid-cols-3 border-b border-border">
          <Kpi
            label="Active series"
            value={String(activeSeries)}
            state={libraryState}
            onRetry={() => void library.refetch()}
          />
          <Kpi
            label="Issues"
            value={String(totalIssues)}
            state={libraryState}
            onRetry={() => void library.refetch()}
            borderLeft
          />
          <Kpi
            label="Completion"
            value={`${completion.toFixed(1)}%`}
            state={libraryState}
            onRetry={() => void library.refetch()}
            borderLeft
          />
        </div>

        {/* Operational summaries */}
        <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] border-b border-border min-h-[320px]">
          {/* Recent history */}
          <section className="px-5 py-4 lg:border-r lg:border-border">
            <PanelHeader
              title="Recent activity"
              meta={`${countMeta(activityState, activityEvents.length, "event")} · ${activityDays} days`}
              action={{
                label: "open history →",
                to: "/activity?view=history",
              }}
            />

            <PanelBody
              state={activityState}
              label="Recent activity"
              skeleton={<PanelSkeleton rows={5} />}
              empty={
                <>
                  no activity in the last {activityDays} days —{" "}
                  <Link
                    to="/activity?view=history"
                    className="hover:text-foreground"
                  >
                    open full history
                  </Link>
                </>
              }
              onRetry={() => void activity.refetch()}
              isRetrying={activity.isFetching}
            >
              {() => (
                <div className="font-mono text-[11px]">
                  {activityEvents.map((d, i) => {
                    const action = d.Status?.toLowerCase() || "—";
                    const color = action.includes("down")
                      ? "var(--chart-4)"
                      : action.includes("post") || action.includes("import")
                        ? "var(--status-active)"
                        : action.includes("snatch") || action.includes("queue")
                          ? "var(--status-paused)"
                          : "var(--muted-foreground)";
                    return (
                      <div
                        key={`${d.ComicID}-${d.IssueID}-${i}`}
                        className="grid items-center gap-2 py-1.5"
                        style={{
                          gridTemplateColumns:
                            "120px 90px minmax(180px, 1fr) 140px",
                          borderTop:
                            i > 0
                              ? "1px solid var(--border-soft, var(--border))"
                              : "none",
                        }}
                      >
                        <RelativeTime value={d.DateAdded} />
                        <span className="uppercase truncate" style={{ color }}>
                          {action}
                        </span>
                        <div className="flex items-center gap-2 min-w-0">
                          {d.ComicID && (
                            <img
                              src={`/api/metadata/art/${d.ComicID}`}
                              alt=""
                              className="w-4 h-6 object-cover rounded-[1px] shrink-0"
                              onError={(e) => {
                                e.currentTarget.style.visibility = "hidden";
                              }}
                            />
                          )}
                          <Link
                            to={`/library/${d.ComicID}`}
                            className="font-sans text-foreground truncate hover:text-[var(--primary)]"
                          >
                            {d.ComicName} #{d.Issue_Number}
                          </Link>
                        </div>
                        <span className="text-muted-foreground truncate">
                          {d.Provider || "—"}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </PanelBody>
          </section>

          {/* This week */}
          <section className="px-5 py-4">
            <PanelHeader
              title="This week"
              meta={countMeta(
                upcomingState,
                upcomingReleases.length,
                "release",
              )}
              action={{ label: "view mine →", to: "/releases?view=mine" }}
            />

            <PanelBody
              state={upcomingState}
              label="This week"
              skeleton={<PanelSkeleton rows={4} rowHeight={41} />}
              empty="nothing upcoming this week"
              onRetry={() => void upcoming.refetch()}
              isRetrying={upcoming.isFetching}
            >
              {() =>
                upcomingReleases.map((u, i) => (
                  <div
                    key={`${u.ComicID}-${u.IssueNumber}-${i}`}
                    className="flex items-center gap-2.5 py-2.5"
                    style={{
                      borderTop:
                        i > 0
                          ? "1px solid var(--border-soft, var(--border))"
                          : "none",
                    }}
                  >
                    <div className="font-mono text-[10px] text-muted-foreground w-12 shrink-0">
                      {u.IssueDate?.slice(5) || "—"}
                    </div>
                    <div className="flex-1 min-w-0">
                      <Link
                        to={`/library/${u.ComicID}`}
                        className="text-[12px] truncate block hover:text-[var(--primary)]"
                      >
                        {u.ComicName}
                      </Link>
                      <div className="font-mono text-[10px] text-muted-foreground">
                        #{u.IssueNumber}
                      </div>
                    </div>
                    <div className="font-mono text-[10px] text-muted-foreground">
                      {u.Status || "auto"}
                    </div>
                  </div>
                ))
              }
            </PanelBody>

            <div className="mt-4 p-3 rounded-[6px] border border-border bg-card">
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <div className="mono-label">Recent chats</div>
                <Link
                  to="/chat"
                  className="font-mono text-[10px] text-primary hover:underline"
                >
                  all →
                </Link>
              </div>
              <PanelBody
                state={chatsState}
                label="Recent chats"
                skeleton={<PanelSkeleton rows={3} rowHeight={33} />}
                empty="no saved chats yet"
                onRetry={() => void chatThreadsQuery.refetch()}
                isRetrying={chatThreadsQuery.isFetching}
              >
                {() =>
                  recentChats.map((thread) => (
                    <Link
                      key={thread.id}
                      to={`/chat/${thread.id}`}
                      className="block px-2 py-1.5 -mx-1 rounded-[6px] hover:bg-accent"
                    >
                      <div className="text-[12px] font-medium truncate">
                        {thread.title}
                      </div>
                      <div className="mono-meta text-[10px]">
                        {thread.message_count} msgs ·{" "}
                        <RelativeTime value={thread.updated_at} />
                      </div>
                    </Link>
                  ))
                }
              </PanelBody>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
