import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Activity,
  ExternalLink,
  MoreHorizontal,
  Pause,
  Play,
  RefreshCw,
  Search,
  TextSearch,
  Trash2,
} from "lucide-react";
import StatusBadge from "@/components/StatusBadge";
import { SeriesContentKind } from "@/components/series/SeriesContentKind";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { ReleaseReviewSheet } from "@/components/releases/ReleaseReviewSheet";
import { useInteractiveReview } from "@/hooks/useInteractiveSearch";
import {
  useConfirmSearchMissing,
  useDeleteSeries,
  usePauseSeries,
  useRefreshSeries,
  useRetrySearchRun,
  useResumeSeries,
  useSearchMissingPreview,
  useSearchRun,
  useSeriesDetail,
  useUpdateSeriesSearchSettings,
  useUpdateSeriesContentKind,
} from "@/hooks/useSeries";
import type {
  ComicOrManga,
  Issue,
  ReleaseReviewIssue,
  SearchMissingPreview,
  SearchMissingResult,
  ContentType,
} from "@/types";
import { displayComicDate, pickComicDate } from "@/lib/format";
import { seriesCoverSrc, seriesSyncLabel } from "@/lib/series-utils";

type IssueFilter = "all" | "have" | "missing" | "monitored";

function getIssueStatus(issue: Issue): string {
  return issue.displayState ?? issue.status ?? issue.Status ?? "Unknown";
}

function isIssueOwned(issue: Issue): boolean {
  if (typeof issue.owned === "boolean") return issue.owned;
  const status = getIssueStatus(issue).toLowerCase();
  return status === "downloaded" || status === "archived";
}

function isIssueInFlight(issue: Issue): boolean {
  if (typeof issue.inFlight === "boolean") return issue.inFlight;
  const status = getIssueStatus(issue).toLowerCase();
  return status === "reserved" || status === "snatched";
}

function isIssueMissing(issue: Issue): boolean {
  if (typeof issue.missing === "boolean") return issue.missing;
  return !isIssueOwned(issue) && !isIssueInFlight(issue);
}

function isIssueMonitored(issue: Issue): boolean {
  if (typeof issue.monitored === "boolean") return issue.monitored;
  const intent = issue.acquisitionIntent?.toLowerCase();
  return intent !== "skipped" && intent !== "ignored";
}

type LedgerKind = "annual" | "chapter" | "volume";

function hasLedgerNumber(value?: string | number | null): boolean {
  return value !== null && value !== undefined && String(value).trim() !== "";
}

/**
 * What a ledger row actually is, read off the row rather than the series.
 *
 * The row shape is not implied by the content kind: a ComicVine manga models
 * the English volumes as its issues, so every row carries a volume number and
 * no chapter number, while a MangaDex ledger is chapters. Labelling anything
 * manga "Chapters" therefore told a volume ledger it was something it is not,
 * and the type column stayed blank for exactly the series that needed it.
 *
 * Chapter wins over volume because a chapter number is the more specific
 * claim: a MangaDex chapter row also carries the volume that contains it,
 * while a volume row has no chapter number to offer.
 *
 * A ComicVine manga writes neither: it models the English volumes as the
 * series' issues, so the volume lands in Issue_Number and VolumeNumber stays
 * null. On a manga ledger a bare number is therefore a volume, which is why
 * this needs the content kind — on a comic ledger the same row is an issue.
 */
function getLedgerKind(issue: Issue, isManga: boolean): LedgerKind | null {
  if (issue.annual) return "annual";
  if (hasLedgerNumber(issue.chapterNumber)) return "chapter";
  if (hasLedgerNumber(issue.volumeNumber)) return "volume";
  if (isManga && hasLedgerNumber(issue.number ?? issue.Issue_Number)) {
    return "volume";
  }
  return null;
}

const LEDGER_KIND_LABEL: Record<LedgerKind, string> = {
  annual: "Annual",
  chapter: "Chapter",
  volume: "Volume",
};

function getSeparateIntent(issue: Issue): string | null {
  const intent = issue.acquisitionIntent?.toLowerCase();
  if (!intent || intent === "policy" || issue.intentExplicit === false) {
    return null;
  }
  return getIssueStatus(issue).toLowerCase() === intent ? null : intent;
}

const ROUTE_REASON_COPY: Record<string, string> = {
  no_viable_acquisition_route:
    "No download route is configured yet. Enable a DDL, Usenet, or torrent route in Settings.",
  route_health_unavailable:
    "Route health could not be read. Check the server logs, then refresh this preview.",
  disabled:
    "Every download route is disabled. Enable one in Settings, along with at least one provider.",
  provider_not_configured:
    "No Usenet indexer is configured. Add and enable one in Search settings.",
  provider_disabled:
    "Usenet indexers are configured but disabled. Enable one in Search settings.",
  downloader_disabled:
    "The Usenet download client is disabled. Choose one in Download client settings.",
  client_not_ready:
    "The download client is missing its host or API key. Finish configuring it in Settings.",
  path_not_ready:
    "The configured download directory does not exist on the server. Check the path and any container mounts.",
  providers_temporarily_blocked:
    "Every provider is in a temporary backoff. This clears on its own — try again shortly.",
  unsupported_restart_correlation:
    "The selected download client cannot correlate downloads across a restart. Choose a client that can.",
};

const ROUTE_REASON_FIX: Record<string, { label: string; to: string }> = {
  provider_not_configured: {
    label: "Open search settings",
    to: "/settings?section=search",
  },
  provider_disabled: {
    label: "Open search settings",
    to: "/settings?section=search",
  },
  downloader_disabled: {
    label: "Open download client settings",
    to: "/settings?section=clients",
  },
  client_not_ready: {
    label: "Open download client settings",
    to: "/settings?section=clients",
  },
  path_not_ready: {
    label: "Open download client settings",
    to: "/settings?section=clients",
  },
};

function formatRouteReason(reason?: string | null): string {
  if (!reason) return "No safe acquisition route is currently ready.";
  return (
    ROUTE_REASON_COPY[reason] ??
    `Search is blocked: ${reason.replace(/_/g, " ")}.`
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Unable to load the search preview.";
}

function pluralize(count: number, singular: string): string {
  return `${count} ${singular}${count === 1 ? "" : "s"}`;
}

const ISSUE_GRID_COLS =
  "grid-cols-[72px_42px_minmax(220px,1fr)_130px_110px_190px_36px]";

function toReleaseReviewIssue(
  issue: Issue,
  seriesName: string,
): ReleaseReviewIssue {
  return {
    IssueNumber: issue.number ?? issue.Issue_Number,
    Issue_Number: issue.Issue_Number,
    ComicName: issue.ComicName ?? issue.comicName ?? seriesName,
    Status: issue.Status ?? issue.status,
    annual: Boolean(issue.annual),
  };
}

function interactiveSearchLabel(issue: Issue): string {
  const issueName = issue.name ?? issue.IssueName;
  const issueNumber = issue.number ?? issue.Issue_Number;
  const fallback =
    `${issue.annual ? "Annual" : "Issue"} ${issueNumber ?? ""}`.trim();
  return `Interactive Search for ${issueName || fallback}`;
}

export default function SeriesDetailPage() {
  const { comicId } = useParams<{ comicId: string }>();
  const navigate = useNavigate();
  const { addToast } = useToast();
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [filter, setFilter] = useState<IssueFilter>("all");
  const [searchDialogOpen, setSearchDialogOpen] = useState(false);
  const [preview, setPreview] = useState<SearchMissingPreview | null>(null);
  const [searchOutcome, setSearchOutcome] =
    useState<SearchMissingResult | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searchRunId, setSearchRunId] = useState<string | null>(null);

  const { data: seriesData, isLoading, error } = useSeriesDetail(comicId);
  const pauseMutation = usePauseSeries();
  const resumeMutation = useResumeSeries();
  const refreshMutation = useRefreshSeries();
  const deleteMutation = useDeleteSeries();
  const searchPreview = useSearchMissingPreview(comicId);
  const confirmSearch = useConfirmSearchMissing();
  const searchRun = useSearchRun(searchRunId);
  const retrySearchRun = useRetrySearchRun();
  const searchSettingsMutation = useUpdateSeriesSearchSettings();
  const contentKindMutation = useUpdateSeriesContentKind();
  const { startReview, reviewSheetProps } = useInteractiveReview();

  const fetchSearchPreview = async () => {
    setPreview(null);
    setSearchError(null);
    setSearchOutcome(null);
    setSearchRunId(null);
    try {
      const result = await searchPreview.refetch();
      if (result.error) {
        setSearchError(errorMessage(result.error));
      } else if (result.data) {
        setPreview(result.data);
      } else {
        setSearchError("The search preview did not return a result.");
      }
    } catch (previewError) {
      setSearchError(errorMessage(previewError));
    }
  };

  const handleOpenSearch = () => {
    setSearchDialogOpen(true);
    void fetchSearchPreview();
  };

  const handleSearchDialogChange = (open: boolean) => {
    setSearchDialogOpen(open);
    if (!open) setSearchRunId(null);
  };

  const handleConfirmSearch = async () => {
    if (!comicId || !preview?.preview_token || !preview.fingerprint) return;
    setSearchError(null);
    try {
      const result = await confirmSearch.mutateAsync({
        comicId,
        previewToken: preview.preview_token,
        fingerprint: preview.fingerprint,
      });
      setSearchOutcome(result);
      setSearchRunId(result.run_id ?? null);
    } catch (confirmationError) {
      setSearchError(errorMessage(confirmationError));
    }
  };

  const handleRetrySearch = async () => {
    if (!searchRunId) return;
    setSearchError(null);
    try {
      const result = await retrySearchRun.mutateAsync(searchRunId);
      setSearchOutcome((current) =>
        current
          ? {
              ...current,
              status:
                result.status === "partial"
                  ? "pending_dispatch"
                  : result.success
                    ? "accepted"
                    : "failed",
              message: result.message,
            }
          : current,
      );
    } catch (retryError) {
      setSearchError(errorMessage(retryError));
    }
  };

  if (isLoading) {
    return (
      <div className="p-5 space-y-4">
        <Skeleton className="h-6 w-64" />
        <div className="grid gap-7 md:grid-cols-[140px_minmax(0,1fr)] xl:grid-cols-[140px_minmax(0,1fr)_260px]">
          <Skeleton className="aspect-[2/3] w-[140px]" />
          <div className="space-y-3">
            <Skeleton className="h-8 w-2/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-4/5" />
          </div>
          <Skeleton className="h-40 w-full md:col-span-2 xl:col-span-1" />
        </div>
      </div>
    );
  }

  if (error || !seriesData) {
    return (
      <div className="p-5">
        <div
          className="rounded-[6px] border p-4"
          style={{
            borderColor:
              "color-mix(in oklab, var(--status-error) 30%, transparent)",
            background: "var(--status-error-bg)",
            color: "var(--status-error)",
          }}
        >
          <div className="mb-1 font-semibold">Failed to load series</div>
          <div className="text-[12px]">
            {error?.message || "Series not found."}
          </div>
          <Link
            to="/library"
            className="mt-3 inline-block font-mono text-[11px] underline"
          >
            ← back to library
          </Link>
        </div>
      </div>
    );
  }

  const comic: ComicOrManga = Array.isArray(seriesData.comic)
    ? seriesData.comic[0]
    : seriesData.comic;
  const issues = seriesData.issues ?? [];
  const annuals = seriesData.annuals ?? [];
  const allIssues = [
    ...issues.map((issue) => ({ ...issue, annual: Boolean(issue.annual) })),
    ...annuals.map((issue) => ({ ...issue, annual: true })),
  ];
  const summary = seriesData.summary;
  const total = summary?.total ?? allIssues.length;
  const have = summary?.owned ?? allIssues.filter(isIssueOwned).length;
  const missing = summary?.missing ?? allIssues.filter(isIssueMissing).length;
  const reviewableMissing = summary?.eligible ?? missing;
  const monitored =
    summary?.monitored ?? allIssues.filter(isIssueMonitored).length;
  const inFlight =
    summary?.inFlight ?? allIssues.filter(isIssueInFlight).length;
  const annualCount =
    summary?.annuals ?? allIssues.filter((issue) => issue.annual).length;
  const completionPct =
    summary?.completionPercent ??
    (total > 0 ? Math.round((have / total) * 100) : 0);
  const isPaused = comic.Status?.toLowerCase() === "paused";
  const allowPacks = comic.AllowPacks === 1 || comic.AllowPacks === "1";
  const ignoreType = Boolean(comic.IgnoreType);
  const coverSrc = seriesCoverSrc(comic.ComicID);

  const handleSearchSettingChange = async (
    setting: "allowPacks" | "ignoreType",
    value: boolean,
  ) => {
    if (!comicId) return;
    try {
      await searchSettingsMutation.mutateAsync({
        comicId,
        ...(setting === "allowPacks"
          ? { allowPacks: value }
          : { ignoreType: value }),
      });
    } catch {
      addToast({
        type: "error",
        title: "Error",
        description: "Failed to update search settings",
      });
    }
  };
  const handleMangaModeChange = async (
    setting: "bareNumberMode" | "monitorMode",
    value: string,
  ) => {
    if (!comicId) return;
    try {
      await searchSettingsMutation.mutateAsync({
        comicId,
        ...(setting === "bareNumberMode"
          ? {
              bareNumberMode: value as "auto" | "volumes" | "chapters",
            }
          : {
              monitorMode: value as "blended" | "volumes" | "chapters",
            }),
      });
    } catch {
      addToast({
        type: "error",
        title: "Error",
        description: "Failed to update search settings",
      });
    }
  };
  // Boolean() because the optional chains make this boolean | undefined, and
  // getLedgerKind takes it as a real argument rather than a truthiness test.
  const isManga = Boolean(
    comic.ContentType === "manga" ||
    comicId?.startsWith("md-") ||
    comicId?.startsWith("mal-"),
  );
  const contentKind: ContentType = isManga ? "manga" : "comic";
  const volumeCount = allIssues.filter(
    (issue) => getLedgerKind(issue, isManga) === "volume",
  ).length;
  const chapterCount = allIssues.filter(
    (issue) => getLedgerKind(issue, isManga) === "chapter",
  ).length;
  // A blended manga ledger holds both, so name both rather than picking one.
  // Falling back to the content kind only when no row carries either number
  // keeps a synthesised placeholder ledger reading as chapters, as before.
  const ledgerLabel =
    volumeCount && chapterCount
      ? "Volumes & chapters"
      : volumeCount
        ? "Volumes"
        : chapterCount
          ? "Chapters"
          : isManga
            ? "Chapters"
            : "Issues";
  const hasArcs = allIssues.some((issue) => Boolean(issue.Arc));
  const ledgerFacets: string[] = [];
  if (volumeCount && chapterCount) {
    ledgerFacets.push(`volumes: ${volumeCount}`, `chapters: ${chapterCount}`);
  }
  if (annualCount) ledgerFacets.push(`annuals: ${annualCount}`);
  // "grouped by arc" used to print unconditionally whenever there were no
  // annuals, including on a ledger whose every arc cell reads "—".
  if (hasArcs) ledgerFacets.push("grouped by arc");
  const provider = comicId?.startsWith("md-")
    ? "MangaDex"
    : comicId?.startsWith("mal-")
      ? "MyAnimeList"
      : "ComicVine";
  const providerCode = comicId?.startsWith("md-")
    ? "md"
    : comicId?.startsWith("mal-")
      ? "mal"
      : "cv";
  const slug = (comic.ComicName || "").toLowerCase().replace(/\s+/g, "-");
  const filteredIssues = allIssues.filter((issue) => {
    if (filter === "have") return isIssueOwned(issue);
    if (filter === "missing") return isIssueMissing(issue);
    if (filter === "monitored") return isIssueMonitored(issue);
    return true;
  });
  const routeViable = preview?.route?.viable !== false;
  const canConfirm = Boolean(
    preview?.canSearch &&
    preview.preview_token &&
    preview.fingerprint &&
    routeViable &&
    !searchError,
  );
  const run = searchRun.data?.run;

  const handlePauseResume = async () => {
    if (!comicId) return;
    try {
      if (isPaused) await resumeMutation.mutateAsync(comicId);
      else await pauseMutation.mutateAsync(comicId);
    } catch {
      addToast({
        type: "error",
        title: "Error",
        description: `Failed to ${isPaused ? "resume" : "pause"} series`,
      });
    }
  };

  const handleRefresh = async () => {
    if (!comicId) return;
    try {
      await refreshMutation.mutateAsync(comicId);
    } catch {
      addToast({
        type: "error",
        title: "Error",
        description: "Failed to refresh series",
      });
    }
  };

  const handleContentKindChange = async (nextKind: ContentType) => {
    if (!comicId || nextKind === contentKind) return;
    try {
      const result = await contentKindMutation.mutateAsync({
        comicId,
        contentType: nextKind,
      });
      addToast({
        type: "success",
        title: "Content kind updated",
        description: result.location_repointed
          ? "This series now uses manga labels. New downloads import under the manga destination. Files already at the previous comics path were not moved."
          : `This series now uses ${nextKind} labels and matching rules.`,
      });
    } catch {
      addToast({
        type: "error",
        title: "Content kind not updated",
        description: "Comicarr could not save this classification. Try again.",
      });
    }
  };

  const handleDelete = async () => {
    if (!comicId) return;
    try {
      await deleteMutation.mutateAsync(comicId);
      navigate("/library");
    } catch {
      addToast({
        type: "error",
        title: "Error",
        description: "Failed to delete series",
      });
    }
  };

  const ghostBtn =
    "inline-flex items-center gap-1.5 rounded-[5px] border px-3 py-1.5 text-[12px] transition-colors hover:bg-secondary/50";

  return (
    <div className="flex h-full flex-col page-transition">
      <div
        className="flex items-center gap-2.5 border-b px-5 py-3.5 font-mono text-[11px]"
        style={{
          borderColor: "var(--border)",
          color: "var(--muted-foreground)",
        }}
      >
        <Link to="/library" className="transition-colors hover:text-foreground">
          library
        </Link>
        <span style={{ color: "var(--text-muted)" }}>/</span>
        <span>{isManga ? "manga" : "comics"}</span>
        <span style={{ color: "var(--text-muted)" }}>/</span>
        <span className="truncate" style={{ color: "var(--foreground)" }}>
          {slug}
        </span>
        <span className="ml-auto hidden shrink-0 sm:inline">
          {providerCode}:{comic.ComicID} · {seriesSyncLabel(comic)}
        </span>
      </div>

      <div
        className="grid gap-7 border-b px-5 py-6 md:grid-cols-[140px_minmax(0,1fr)] xl:grid-cols-[140px_minmax(0,1fr)_260px]"
        style={{ borderColor: "var(--border)" }}
      >
        <div
          className="aspect-[2/3] w-[112px] overflow-hidden rounded-[5px] border md:w-[140px]"
          style={{ borderColor: "var(--border)" }}
        >
          {coverSrc && (
            <img
              src={coverSrc}
              alt={comic.ComicName}
              className="h-full w-full object-cover"
              onError={(event) => {
                event.currentTarget.style.display = "none";
              }}
            />
          )}
        </div>

        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2 font-mono text-[10px] uppercase tracking-[0.08em]">
            <span
              className="rounded-[3px] px-1.5 py-0.5"
              style={{
                background:
                  "color-mix(in oklab, var(--primary) 14%, transparent)",
                color: "var(--primary)",
              }}
            >
              {isManga ? "MANGA" : "COMIC"}
            </span>
            {comic.ComicPublisher && (
              <span style={{ color: "var(--muted-foreground)" }}>
                {comic.ComicPublisher}
              </span>
            )}
            {comic.ComicYear && (
              <>
                <span style={{ color: "var(--text-muted)" }}>·</span>
                <span style={{ color: "var(--muted-foreground)" }}>
                  {comic.ComicYear}
                </span>
              </>
            )}
            <span style={{ color: "var(--text-muted)" }}>·</span>
            <span
              style={{
                color: isPaused ? "var(--text-muted)" : "var(--status-active)",
              }}
            >
              ● {isPaused ? "paused" : "ongoing"}
            </span>
            <span style={{ color: "var(--text-muted)" }}>·</span>
            <span style={{ color: "var(--muted-foreground)" }}>monitored</span>
          </div>

          <h1 className="mb-2 text-[28px] font-bold leading-tight tracking-[-0.02em]">
            {comic.ComicName}
          </h1>

          {seriesData.providerLinks && seriesData.providerLinks.length > 0 ? (
            <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1">
              {seriesData.providerLinks.map((link) => (
                <a
                  key={`${link.provider}-${link.url}`}
                  href={link.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-[12px] font-medium hover:underline"
                  style={{ color: "var(--primary)" }}
                >
                  View on {link.label}
                  <ExternalLink className="h-3 w-3" aria-hidden="true" />
                </a>
              ))}
            </div>
          ) : null}

          {comic.Description && (
            <p
              className="mb-3.5 max-w-[640px] text-[13px] leading-relaxed"
              style={{ color: "var(--muted-foreground)" }}
            >
              {comic.Description}
            </p>
          )}

          <SeriesContentKind
            value={contentKind}
            provider={provider}
            pending={contentKindMutation.isPending}
            onChange={(nextKind) => void handleContentKindChange(nextKind)}
          />

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleOpenSearch}
              disabled={!comicId || searchPreview.isFetching}
              className="inline-flex items-center gap-1.5 rounded-[5px] px-3.5 py-1.5 text-[12px] font-semibold disabled:cursor-not-allowed disabled:opacity-60"
              style={{
                background: "var(--primary)",
                color: "var(--primary-foreground)",
              }}
            >
              <Search className="h-3.5 w-3.5" />
              Search all missing
            </button>
            <button
              type="button"
              onClick={() =>
                comicId
                  ? void startReview(
                      {
                        ComicName: comic.ComicName,
                        Status: comic.Status,
                        scope: "series",
                        missingCount: reviewableMissing,
                      },
                      {
                        entityType: "series",
                        entityId: String(comicId),
                      },
                    )
                  : undefined
              }
              disabled={
                !comicId ||
                reviewableMissing === 0 ||
                reviewSheetProps.startPending
              }
              className={ghostBtn}
              style={{ borderColor: "var(--border)" }}
              aria-label="Interactive Search for missing issues"
            >
              <Search className="h-3.5 w-3.5" />
              Review missing
            </button>
            <button
              type="button"
              onClick={() =>
                comicId
                  ? void startReview(
                      {
                        ComicName: comic.ComicName,
                        Status: comic.Status,
                        scope: "series",
                        missingCount: reviewableMissing,
                        unfiltered: true,
                      },
                      {
                        entityType: "series",
                        entityId: String(comicId),
                        mode: "unfiltered",
                      },
                    )
                  : undefined
              }
              disabled={
                !comicId ||
                reviewableMissing === 0 ||
                reviewSheetProps.startPending
              }
              className={ghostBtn}
              style={{ borderColor: "var(--border)" }}
              aria-label="Browse every indexer's releases for this series"
              title="One bare series-title query per indexer, every returned release shown — indexers without a title search are marked unsupported"
            >
              <TextSearch className="h-3.5 w-3.5" />
              Browse releases
            </button>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={refreshMutation.isPending}
              className={ghostBtn}
              style={{ borderColor: "var(--border)" }}
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${refreshMutation.isPending ? "animate-spin" : ""}`}
              />
              Refresh
            </button>
            {comicId ? (
              <Link
                to={`/activity?scope_type=series&scope_id=${encodeURIComponent(comicId)}`}
                className={ghostBtn}
                style={{ borderColor: "var(--border)" }}
                aria-label="View activity for this series"
              >
                <Activity className="h-3.5 w-3.5" />
                Activity
              </Link>
            ) : null}
            <button
              type="button"
              onClick={handlePauseResume}
              disabled={pauseMutation.isPending || resumeMutation.isPending}
              className={ghostBtn}
              style={{ borderColor: "var(--border)" }}
            >
              {isPaused ? (
                <Play className="h-3.5 w-3.5" />
              ) : (
                <Pause className="h-3.5 w-3.5" />
              )}
              {isPaused ? "Resume" : "Pause"}
            </button>
            {!showDeleteConfirm ? (
              <button
                type="button"
                onClick={() => setShowDeleteConfirm(true)}
                className={ghostBtn}
                style={{
                  borderColor: "var(--border)",
                  color: "var(--muted-foreground)",
                }}
                aria-label="More actions"
              >
                <MoreHorizontal className="h-3.5 w-3.5" />
              </button>
            ) : (
              <>
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={deleteMutation.isPending}
                  className="inline-flex items-center gap-1.5 rounded-[5px] px-3 py-1.5 text-[12px] font-semibold"
                  style={{ background: "var(--status-error)", color: "white" }}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  Confirm delete
                </button>
                <button
                  type="button"
                  onClick={() => setShowDeleteConfirm(false)}
                  className={ghostBtn}
                  style={{ borderColor: "var(--border)" }}
                >
                  Cancel
                </button>
              </>
            )}
          </div>
        </div>

        <div
          className="rounded-[6px] border md:col-span-2 xl:col-span-1"
          style={{ borderColor: "var(--border)", background: "var(--card)" }}
        >
          <div
            className="border-b px-3 py-2.5 font-mono text-[10px] uppercase tracking-[0.1em]"
            style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
          >
            Status
          </div>
          <div className="px-3 py-2.5">
            <div className="mb-1.5 flex items-baseline gap-2">
              <div className="text-[28px] font-bold leading-none tracking-[-0.02em]">
                {completionPct}%
              </div>
              <div
                className="font-mono text-[10px]"
                style={{
                  color:
                    completionPct === 100
                      ? "var(--status-active)"
                      : "var(--muted-foreground)",
                }}
              >
                {completionPct === 100 ? "complete" : "in progress"}
              </div>
            </div>
            <div
              className="mb-2.5 h-1 overflow-hidden rounded-full"
              style={{ background: "var(--border)" }}
            >
              <div
                className="h-full"
                style={{
                  width: `${completionPct}%`,
                  background:
                    completionPct === 100
                      ? "var(--status-active)"
                      : "var(--primary)",
                }}
              />
            </div>
            <div className="grid grid-cols-2 gap-x-3 font-mono text-[10px]">
              {(
                [
                  ["have", String(have)],
                  ["total", String(total)],
                  ["missing", String(missing)],
                  ["in flight", String(inFlight)],
                ] as const
              ).map(([label, value], index) => (
                <div
                  key={label}
                  className="flex justify-between py-1"
                  style={{
                    borderTop: index > 1 ? "1px solid var(--border)" : "none",
                  }}
                >
                  <span style={{ color: "var(--text-muted)" }}>{label}</span>
                  <span>{value}</span>
                </div>
              ))}
            </div>
          </div>
          <div
            className="border-t px-3 py-2.5"
            style={{ borderColor: "var(--border)" }}
          >
            <div
              className="mb-2 font-mono text-[10px] uppercase tracking-[0.1em]"
              style={{ color: "var(--text-muted)" }}
            >
              Search options
            </div>
            {[
              {
                key: "allowPacks" as const,
                label: "Allow packs",
                title:
                  "Accept pack/bundle releases (multi-issue or volume torrents) when searching",
                checked: allowPacks,
              },
              {
                key: "ignoreType" as const,
                label: "Ignore book type",
                title:
                  "Match results even when the release's book type (TPB, GN…) differs from this series",
                checked: ignoreType,
              },
            ].map(({ key, label, title, checked }) => (
              <label
                key={key}
                title={title}
                className="flex cursor-pointer items-center justify-between gap-2 py-1 font-mono text-[10px]"
              >
                <span style={{ color: "var(--text-muted)" }}>{label}</span>
                <Checkbox
                  checked={checked}
                  disabled={searchSettingsMutation.isPending}
                  onCheckedChange={(value) =>
                    void handleSearchSettingChange(key, value)
                  }
                  aria-label={label}
                />
              </label>
            ))}
            {isManga ? (
              <div className="mt-2 grid gap-2">
                <label className="grid gap-1 font-mono text-[10px]">
                  <span style={{ color: "var(--text-muted)" }}>
                    Bare numbers
                  </span>
                  <select
                    aria-label="Bare numbers"
                    className="h-7 rounded-[5px] border bg-background px-2"
                    style={{ borderColor: "var(--border)" }}
                    disabled={searchSettingsMutation.isPending}
                    value={comic.BareNumberMode || "auto"}
                    onChange={(event) =>
                      void handleMangaModeChange(
                        "bareNumberMode",
                        event.target.value,
                      )
                    }
                  >
                    <option value="auto">Auto</option>
                    <option value="volumes">Volumes</option>
                    <option value="chapters">Chapters</option>
                  </select>
                </label>
                <label className="grid gap-1 font-mono text-[10px]">
                  <span style={{ color: "var(--text-muted)" }}>Monitor</span>
                  <select
                    aria-label="Monitor"
                    className="h-7 rounded-[5px] border bg-background px-2"
                    style={{ borderColor: "var(--border)" }}
                    disabled={searchSettingsMutation.isPending}
                    value={comic.MonitorMode || "blended"}
                    onChange={(event) =>
                      void handleMangaModeChange(
                        "monitorMode",
                        event.target.value,
                      )
                    }
                  >
                    <option value="blended">Blended frontier</option>
                    <option value="volumes">Volumes only</option>
                    <option value="chapters">Chapters only</option>
                  </select>
                </label>
              </div>
            ) : null}
          </div>
        </div>
      </div>

      <div
        className="flex flex-wrap items-center gap-3 border-b px-5 py-2.5"
        style={{ borderColor: "var(--border)" }}
      >
        <div className="text-[13px] font-semibold" data-testid="ledger-label">
          {ledgerLabel}
        </div>
        <div
          className="font-mono text-[10px] uppercase tracking-[0.08em]"
          style={{ color: "var(--text-muted)" }}
          data-testid="ledger-facets"
        >
          {ledgerFacets.length
            ? `${total} · ${ledgerFacets.join(" · ")}`
            : total}
        </div>
        <div className="ml-auto flex flex-wrap gap-1.5 font-mono text-[10px]">
          {(
            [
              ["all", `All ${total}`],
              ["have", `Have ${have}`],
              ["missing", `Missing ${missing}`],
              ["monitored", `Monitored ${monitored}`],
            ] as const
          ).map(([key, label]) => {
            const active = filter === key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => setFilter(key)}
                className="rounded-full border px-2 py-0.5 transition-colors"
                style={{
                  borderColor: active ? "var(--primary)" : "var(--border)",
                  color: active ? "var(--primary)" : "var(--muted-foreground)",
                  background: active
                    ? "color-mix(in oklab, var(--primary) 12%, transparent)"
                    : "transparent",
                }}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-auto">
        <div className="min-w-[720px]">
          <div
            className={`sticky top-0 z-10 grid ${ISSUE_GRID_COLS} gap-3 border-b px-5 py-2 font-mono text-[10px] uppercase tracking-[0.1em]`}
            style={{
              borderColor: "var(--border)",
              color: "var(--text-muted)",
              background: "var(--card)",
            }}
          >
            <div>type</div>
            <div>#</div>
            <div>title</div>
            <div>arc</div>
            <div>date</div>
            <div>state</div>
            <div className="sr-only">search</div>
          </div>

          {filteredIssues.length === 0 ? (
            <div
              className="px-5 py-8 text-center font-mono text-[11px]"
              style={{ color: "var(--text-muted)" }}
            >
              no issues to display
            </div>
          ) : (
            filteredIssues.map((issue) => {
              const issueId = issue.id ?? issue.IssueID;
              const issueNumber = issue.number ?? issue.Issue_Number;
              const issueName = issue.name ?? issue.IssueName;
              const issueDate = pickComicDate(
                issue.releaseDate,
                issue.ReleaseDate,
                issue.issueDate,
                issue.IssueDate,
              );
              const status = getIssueStatus(issue);
              const separateIntent = getSeparateIntent(issue);
              const ledgerKind = getLedgerKind(issue, isManga);
              return (
                <div
                  key={`${issue.annual ? "annual" : "issue"}-${issueId}`}
                  className={`grid ${ISSUE_GRID_COLS} items-center gap-3 border-b px-5 py-2 text-[12px]`}
                  style={{ borderColor: "var(--border)" }}
                >
                  <div>
                    {ledgerKind && (
                      <span
                        className="rounded-[3px] px-1.5 py-0.5 font-mono text-[9px] uppercase"
                        style={{
                          background:
                            "color-mix(in oklab, var(--primary) 12%, transparent)",
                          color: "var(--primary)",
                        }}
                      >
                        {LEDGER_KIND_LABEL[ledgerKind]}
                      </span>
                    )}
                  </div>
                  <div
                    className="font-mono"
                    style={{ color: "var(--muted-foreground)" }}
                  >
                    #{String(issueNumber ?? "").padStart(2, "0")}
                  </div>
                  <div className="min-w-0 truncate">
                    <Link
                      to={`/library/${comicId}/issue/${issueId}`}
                      className="transition-colors hover:text-primary"
                    >
                      {issueName ||
                        `${issue.annual ? "Annual" : "Issue"} ${issueNumber}`}
                    </Link>
                  </div>
                  <div
                    className="truncate text-[11px]"
                    style={{ color: "var(--muted-foreground)" }}
                  >
                    {issue.Arc || "—"}
                  </div>
                  <div
                    className="font-mono text-[10px]"
                    style={{ color: "var(--muted-foreground)" }}
                  >
                    {displayComicDate(issueDate)}
                  </div>
                  <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                    <StatusBadge status={status} />
                    {separateIntent && (
                      <span
                        className="font-mono text-[9px] lowercase"
                        style={{ color: "var(--muted-foreground)" }}
                      >
                        intent: {separateIntent}
                      </span>
                    )}
                  </div>
                  <div className="flex justify-end">
                    <button
                      type="button"
                      className="inline-flex size-7 items-center justify-center rounded-[5px] transition-colors hover:bg-secondary/50"
                      style={{ color: "var(--muted-foreground)" }}
                      aria-label={interactiveSearchLabel(issue)}
                      title="Interactive Search"
                      disabled={!issueId}
                      onClick={() =>
                        void startReview(
                          toReleaseReviewIssue(issue, comic.ComicName),
                          {
                            entityType: issue.annual ? "annual" : "issue",
                            entityId: String(issueId ?? ""),
                          },
                        )
                      }
                    >
                      <Search className="h-3.5 w-3.5" aria-hidden="true" />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      <Dialog open={searchDialogOpen} onOpenChange={handleSearchDialogChange}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Search missing issues</DialogTitle>
            <DialogDescription>
              Review the current selection before Comicarr creates one durable
              search run.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3" aria-live="polite">
            {searchPreview.isFetching && (
              <>
                <Skeleton className="h-16 w-full" />
                <Skeleton className="h-10 w-3/4" />
              </>
            )}

            {searchError && (
              <div
                role="alert"
                className="rounded-[5px] border p-3 text-[12px]"
                style={{
                  borderColor:
                    "color-mix(in oklab, var(--status-error) 35%, transparent)",
                  background: "var(--status-error-bg)",
                  color: "var(--status-error)",
                }}
              >
                <div className="font-semibold">
                  Unable to confirm this search
                </div>
                <div className="mt-1">{searchError}</div>
              </div>
            )}

            {preview && !searchOutcome && !searchPreview.isFetching && (
              <>
                <div
                  className="rounded-[5px] border p-3 text-[12px]"
                  style={{
                    borderColor: "var(--border)",
                    background: "var(--card)",
                  }}
                >
                  <div className="font-semibold">
                    {pluralize(preview.eligibleCount, "eligible issue")} will be
                    searched.
                  </div>
                  <div
                    className="mt-1"
                    style={{ color: "var(--muted-foreground)" }}
                  >
                    {pluralize(preview.excludedCount, "issue")} are excluded
                    from this run.
                  </div>
                  {preview.eligible?.some(
                    (item) => item.entityType === "annual",
                  ) && (
                    <div
                      className="mt-2 font-mono text-[10px]"
                      style={{ color: "var(--primary)" }}
                    >
                      Includes annuals when they are eligible.
                    </div>
                  )}
                </div>

                {!routeViable ? (
                  <div
                    role="alert"
                    className="rounded-[5px] border p-3 text-[12px]"
                    style={{
                      borderColor:
                        "color-mix(in oklab, var(--status-paused) 35%, transparent)",
                      background: "var(--status-paused-bg)",
                    }}
                  >
                    <div className="font-semibold">
                      Search configuration needs attention
                    </div>
                    <div
                      className="mt-1"
                      style={{ color: "var(--muted-foreground)" }}
                    >
                      {formatRouteReason(preview.route?.reason)}
                    </div>
                    {preview.route?.reason && (
                      <div
                        className="mt-2 font-mono text-[10px]"
                        style={{ color: "var(--text-muted)" }}
                      >
                        {preview.route.reason}
                      </div>
                    )}
                    {preview.route?.reason &&
                      ROUTE_REASON_FIX[preview.route.reason] && (
                        <Button
                          asChild
                          variant="outline"
                          size="sm"
                          className="mt-3"
                        >
                          <Link to={ROUTE_REASON_FIX[preview.route.reason].to}>
                            {ROUTE_REASON_FIX[preview.route.reason].label}
                          </Link>
                        </Button>
                      )}
                  </div>
                ) : preview.eligibleCount === 0 ? (
                  <div
                    className="rounded-[5px] border p-3 text-[12px]"
                    style={{
                      borderColor: "var(--border)",
                      color: "var(--muted-foreground)",
                    }}
                  >
                    No eligible missing issues remain to search.
                  </div>
                ) : (
                  <p
                    className="text-[12px]"
                    style={{ color: "var(--muted-foreground)" }}
                  >
                    Confirmation queues this exact preview once. The run owns
                    retries and outcome tracking.
                  </p>
                )}
              </>
            )}

            {searchOutcome && (
              <div
                className="rounded-[5px] border p-3 text-[12px]"
                style={{
                  borderColor: "var(--border)",
                  background: "var(--card)",
                }}
              >
                <div className="font-semibold">
                  {searchOutcome.run_id
                    ? "Search run accepted"
                    : "Search result"}
                </div>
                <div
                  className="mt-1"
                  style={{ color: "var(--muted-foreground)" }}
                >
                  {searchOutcome.message ||
                    (searchOutcome.status === "noop"
                      ? "No eligible missing issues remain to search."
                      : "The search request was recorded.")}
                </div>
                {run && (
                  <div
                    className="mt-3 rounded-[4px] border px-2.5 py-2 font-mono text-[10px]"
                    style={{ borderColor: "var(--border)" }}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span style={{ color: "var(--text-muted)" }}>
                        run state
                      </span>
                      <span>{run.completion_state}</span>
                    </div>
                    <div
                      className="mt-1"
                      style={{ color: "var(--muted-foreground)" }}
                    >
                      {run.succeeded_count} matched · {run.no_match_count} no
                      match
                      {run.failed_count ? ` · ${run.failed_count} failed` : ""}
                      {run.blocked_count
                        ? ` · ${run.blocked_count} blocked`
                        : ""}
                    </div>
                  </div>
                )}
                {searchRun.isLoading && (
                  <div
                    className="mt-3 font-mono text-[10px]"
                    style={{ color: "var(--text-muted)" }}
                  >
                    Checking run outcome…
                  </div>
                )}
                {searchRun.isError && (
                  <div
                    role="alert"
                    className="mt-3"
                    style={{ color: "var(--status-error)" }}
                  >
                    Unable to refresh the run outcome. It remains recorded and
                    can be checked from Activity.
                  </div>
                )}
                {searchOutcome.status === "pending_dispatch" && searchRunId && (
                  <Button
                    type="button"
                    variant="outline"
                    className="mt-3"
                    onClick={() => void handleRetrySearch()}
                    disabled={retrySearchRun.isPending}
                  >
                    {retrySearchRun.isPending
                      ? "Retrying queue handoff…"
                      : "Retry queue handoff"}
                  </Button>
                )}
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => handleSearchDialogChange(false)}
            >
              {searchOutcome ? "Close" : "Cancel"}
            </Button>
            {!searchOutcome && (searchError || !routeViable) && (
              <Button
                type="button"
                variant="outline"
                onClick={() => void fetchSearchPreview()}
                disabled={searchPreview.isFetching}
              >
                Refresh preview
              </Button>
            )}
            {!searchOutcome && preview && (
              <Button
                type="button"
                onClick={() => void handleConfirmSearch()}
                disabled={!canConfirm || confirmSearch.isPending}
              >
                {confirmSearch.isPending ? "Confirming…" : "Confirm search"}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ReleaseReviewSheet {...reviewSheetProps} />
    </div>
  );
}
