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
import LibraryRow from "@/components/dashboard/LibraryRow";
import NeedsAttentionBand from "@/components/dashboard/NeedsAttentionBand";
import RecentActivity from "@/components/dashboard/RecentActivity";
import { panelState, type PanelState } from "@/lib/panelState";
import { Kbd } from "@/components/ui/kbd";
import { useToast } from "@/components/ui/toast";
import {
  useDashboardLibrary,
  useDashboardScanTargets,
  useDashboardUpcoming,
} from "@/hooks/useDashboard";
import {
  useComicScan,
  useComicScanProgress,
  useMangaScan,
  useMangaScanProgress,
} from "@/hooks/useImport";

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

export default function DashboardPage() {
  const library = useDashboardLibrary();
  const upcoming = useDashboardUpcoming();
  const scanTargets = useDashboardScanTargets();
  const navigate = useNavigate();
  const [question, setQuestion] = useState("");

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
  const upcomingReleases = upcoming.data?.releases ?? [];

  const activeSeries = stats?.total_series ?? 0;
  const totalIssues = stats?.total_issues ?? 0;

  const libraryState = panelState(library, false);
  const upcomingState = panelState(upcoming, upcomingReleases.length === 0);

  const comicScanning = comicScanProgress?.status === "scanning";
  const mangaScanning = mangaScanProgress?.status === "scanning";
  const scanPending =
    comicScan.isPending ||
    mangaScan.isPending ||
    comicScanning ||
    mangaScanning;
  const canScan = Boolean(scanTargets.data?.comic || scanTargets.data?.manga);
  const scanTitle = canScan
    ? "Scan configured comic and manga libraries"
    : "Configure a library directory first";

  const summary = summarize(
    libraryState,
    "library",
    `${activeSeries.toLocaleString()} series · ${totalIssues.toLocaleString()} issues`,
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
        message: `${
          started === 2 ? "Comic and manga library scans" : "Library scan"
        } started.`,
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

      {/* Question 2 — what needs me — and, beside it, how much work is moving
          (dashboard-spec.md §3.2, §3.3, §4). One row, but two queries: each
          side still reports its own unavailability and retries alone, so a
          broken band can never take the in-flight count down with it. */}
      <div
        className="border-b border-border flex flex-col lg:flex-row lg:items-start"
        data-testid="attention-inflight-row"
      >
        <div className="min-w-0 flex-1 border-b border-border lg:border-b-0">
          <NeedsAttentionBand />
        </div>
        <div className="shrink-0 lg:border-l lg:border-border">
          <InFlightLine />
        </div>
      </div>

      {/* Everything below the actionable bands scrolls inside the page column. */}
      <div className="flex-1 min-h-0 overflow-auto">
        {/* Question 3 — what is happening. On narrow viewports these stack in
            the same priority order: activity first, then what is coming. */}
        <div
          className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] border-b border-border min-h-[320px]"
          data-testid="middle-columns"
        >
          {/* Narrative recent activity (dashboard-spec.md §3.4) */}
          <RecentActivity />

          {/* This week */}
          <section className="px-5 py-4" data-testid="this-week">
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
          </section>
        </div>

        {/* Question 4 — what the library is. Ambient, one row, and deliberately
            far from the health band (dashboard-spec.md §3.6). */}
        <LibraryRow />

        {/* Ask — a feature entry point, not an answer to any of §2's questions,
            so it sits last (dashboard-spec.md §3.8). The suggestion chips are
            gone: "Anything stuck in the queue?" was health reporting, and the
            health band now does that properly. */}
        <div className="px-5 py-3.5" data-testid="ask-bar">
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
              className="min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-muted-foreground"
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
        </div>
      </div>
    </div>
  );
}
