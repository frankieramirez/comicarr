import { useState, type SubmitEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAiStatus } from "@/hooks/useAiStatus";
import { ArrowUp, RefreshCw } from "lucide-react";
import {
  PanelBody,
  PanelSkeleton,
  PanelUnavailable,
  SectionHeader,
} from "@/components/dashboard/DashboardPanel";
import {
  MostWanted,
  RecentlyAdded,
} from "@/components/dashboard/LibraryHighlights";
import HealthBand from "@/components/dashboard/HealthBand";
import InFlightLine from "@/components/dashboard/InFlightLine";
import NeedsAttentionBand from "@/components/dashboard/NeedsAttentionBand";
import RecentActivity from "@/components/dashboard/RecentActivity";
import { panelState, type PanelState } from "@/lib/panelState";
import PageHeader from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
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
  const aiConfigured = Boolean(useAiStatus().data?.configured);

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
      <PageHeader
        title="Dashboard"
        meta={summary}
        actions={
          scanTargets.isError ? (
            <PanelUnavailable
              label="Scan targets"
              onRetry={() => void scanTargets.refetch()}
              isRetrying={scanTargets.isFetching}
            />
          ) : (
            <Button
              type="button"
              variant="outline"
              size="toolbar"
              onClick={() => void handleLibraryScan()}
              disabled={!canScan || scanPending}
              title={scanTitle}
            >
              <RefreshCw className={scanPending ? "animate-spin" : ""} />
              {scanPending ? "Scanning…" : "Scan libraries"}
            </Button>
          )
        }
      />

      <div className="flex-1 min-h-0 overflow-auto">
        <div
          className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_352px] lg:grid-rows-[auto_1fr]"
          data-testid="middle-columns"
        >
          {/* Main column, top: what needs me. */}
          <div
            className="min-w-0 px-8 pb-8 pt-2 lg:col-start-1"
            data-testid="attention-inflight-row"
          >
            <NeedsAttentionBand />
          </div>

          {/* Right rail: is it working, what is coming, what just happened. */}
          <aside className="flex flex-col gap-7 border-border-subtle px-8 pb-8 pt-2 lg:col-start-2 lg:row-span-2 lg:row-start-1 lg:border-l">
            <InFlightLine />
            {/* On one column, health follows Needs you directly. */}
            <div className="max-lg:-order-1">
              <HealthBand />
            </div>

            <section data-testid="this-week">
              <SectionHeader
                variant="rail"
                title="This week"
                action={{ label: "Releases", to: "/releases?view=mine" }}
              />
              <PanelBody
                state={upcomingState}
                label="This week"
                skeleton={<PanelSkeleton rows={3} rowHeight={26} />}
                empty="nothing upcoming this week"
                onRetry={() => void upcoming.refetch()}
                isRetrying={upcoming.isFetching}
              >
                {() =>
                  upcomingReleases.map((u, i) => (
                    <Link
                      key={`${u.ComicID}-${u.IssueNumber}-${i}`}
                      to={`/library/${u.ComicID}`}
                      className="flex items-baseline gap-3 py-1 text-[13px] hover:text-foreground"
                    >
                      <span className="min-w-0 flex-1 truncate">
                        {u.ComicName}{" "}
                        <span className="font-mono text-xs text-muted-foreground">
                          #{u.IssueNumber}
                        </span>
                      </span>
                      <span className="mono-meta shrink-0">
                        {u.IssueDate?.slice(5) || "—"}
                      </span>
                    </Link>
                  ))
                }
              </PanelBody>
            </section>

            <RecentActivity />
          </aside>

          {/* Main column, below: the library at a glance. */}
          <div className="flex min-w-0 flex-col gap-8 px-8 pb-8 lg:col-start-1">
            <RecentlyAdded />
            <MostWanted />

            {aiConfigured && (
              <div data-testid="ask-bar">
                <form
                  onSubmit={handleAsk}
                  className="flex items-center gap-2.5 rounded-lg border border-border-strong bg-surface-1 px-3 py-2 focus-within:border-border-emphasis"
                >
                  <input
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    aria-label="Ask about your library"
                    placeholder="Ask about your library"
                    className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                  />
                  <Kbd className="hidden sm:inline-flex">⌘⇧K</Kbd>
                  <button
                    type="submit"
                    aria-label="Ask Comicarr"
                    disabled={!question.trim()}
                    className="flex size-7 shrink-0 items-center justify-center rounded-control bg-act text-act-foreground disabled:opacity-40"
                  >
                    <ArrowUp className="size-3.5" />
                  </button>
                </form>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
