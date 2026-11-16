import { ph, plural, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { SEGMENTED_GROUP, SEGMENTED_ITEM } from "@/lib/segmented";
import { useCallback, useRef, useState, type UIEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Activity,
  ChevronDown,
  ExternalLink,
  MoreHorizontal,
  Pause,
  Plus,
  Play,
  RefreshCw,
  Search,
  TextSearch,
  Trash2,
  ChevronLeft,
} from "lucide-react";
import IssueStatusMenu from "@/components/series/IssueStatusMenu";
import { SeriesContentKind } from "@/components/series/SeriesContentKind";
import { SeriesSearchProviders } from "@/components/series/SeriesSearchProviders";
import { SeriesFolder } from "@/components/series/SeriesFolder";
import { useIsMobile } from "@/hooks/use-mobile";
import { Button, buttonVariants } from "@/components/ui/button";
import { useSearchBlockers } from "@/hooks/useAcquisitionHealth";
import type { SearchBlocker } from "@/lib/searchBlockers";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tab, TabRow } from "@/components/layout/PageHeader";
import { Callout } from "@/components/ui/callout";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { ReleaseReviewSheet } from "@/components/releases/ReleaseReviewSheet";
import { useInteractiveReview } from "@/hooks/useInteractiveSearch";
import {
  useBulkSetIssueStatus,
  useConfirmSearchMissing,
  useDeleteSeries,
  usePauseSeries,
  useRefreshSeries,
  useRetrySearchRun,
  useResumeSeries,
  useSearchMissingPreview,
  useSearchRun,
  useSeriesDetail,
  useSetIssueStatus,
  useUpdateSeriesSearchSettings,
  useUpdateSeriesContentKind,
} from "@/hooks/useSeries";
import { describeBulkResult } from "@/hooks/useQueue";
import type {
  ComicOrManga,
  Issue,
  ReleaseReviewIssue,
  SearchMissingPreview,
  SearchMissingResult,
  SeriesKind,
  SettableIssueStatus,
} from "@/types";
import { isNotFoundError } from "@/lib/api";
import { displayComicDate, pickComicDate } from "@/lib/format";
import { seriesCoverSrc, seriesSyncLabel } from "@/lib/series-utils";
import { DESKTOP_COL } from "@/components/data-table/gridColumns";

type IssueFilter = "all" | "have" | "wanted" | "not_wanted";

function getIssueStatus(issue: Issue): string {
  return issue.displayState ?? issue.status ?? issue.Status ?? t`Unknown`;
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

/** Missing, and auto-search goes after it: what the Wanted page lists. */
function isIssueWanted(issue: Issue): boolean {
  return isIssueMissing(issue) && isIssueMonitored(issue);
}

/** Missing, but skipped or ignored: auto-search leaves it alone. */
function isIssueNotWanted(issue: Issue): boolean {
  return isIssueMissing(issue) && !isIssueMonitored(issue);
}

/**
 * The ledger's word for an issue. "Missing" is the projection's name for a
 * wanted issue with no explicit intent; on screen it is simply Wanted, the
 * word the chips, Wanted page and dashboard use.
 */
function issueLabel(issue: Issue): string {
  const status = getIssueStatus(issue);
  return status === "Missing" ? t`Wanted` : status;
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

const LEDGER_KIND_LABEL = (): Record<LedgerKind, string> => ({
  annual: t`Annual`,
  chapter: t`Chapter`,
  volume: t`Volume`,
});

function getSeparateIntent(issue: Issue): string | null {
  const intent = issue.acquisitionIntent?.toLowerCase();
  if (!intent || intent === "policy" || issue.intentExplicit === false) {
    return null;
  }
  return getIssueStatus(issue).toLowerCase() === intent ? null : intent;
}

const ROUTE_REASON_COPY = (): Record<string, string> => ({
  no_viable_acquisition_route: t`No download route is configured yet. Enable a DDL, Usenet, or torrent route in Settings.`,
  route_health_unavailable: t`Route health could not be read. Check the server logs, then refresh this preview.`,
  disabled: t`Every download route is disabled. Enable one in Settings, along with at least one provider.`,
  provider_not_configured: t`No Usenet indexer is configured. Add and enable one in Search settings.`,
  provider_disabled: t`Usenet indexers are configured but disabled. Enable one in Search settings.`,
  downloader_disabled: t`The Usenet download client is disabled. Choose one in Download client settings.`,
  client_not_ready: t`The download client is missing its host or API key. Finish configuring it in Settings.`,
  path_not_ready: t`The configured download directory does not exist on the server. Check the path and any container mounts.`,
  providers_temporarily_blocked: t`Every provider is in a temporary backoff. This clears on its own — try again shortly.`,
  unsupported_restart_correlation: t`The selected download client cannot correlate downloads across a restart. Choose a client that can.`,
});

const ROUTE_REASON_FIX = (): Record<string, { label: string; to: string }> => ({
  provider_not_configured: {
    label: t`Open search settings`,
    to: "/settings?section=search",
  },
  provider_disabled: {
    label: t`Open search settings`,
    to: "/settings?section=search",
  },
  downloader_disabled: {
    label: t`Open download client settings`,
    to: "/settings?section=clients",
  },
  client_not_ready: {
    label: t`Open download client settings`,
    to: "/settings?section=clients",
  },
  path_not_ready: {
    label: t`Open download client settings`,
    to: "/settings?section=clients",
  },
});

/**
 * The header's primary action. While setup stops every search, a "Search 117
 * missing" button can only fail, so the same spot links to the fix instead.
 */
function SearchMissingButton({
  blocker,
  missing,
  onClick,
  disabled,
  "aria-label": ariaLabel,
}: {
  blocker?: SearchBlocker;
  missing: number;
  onClick: () => void;
  disabled: boolean;
  "aria-label"?: string;
}) {
  if (blocker) {
    return (
      <Link
        to={blocker.fix.to}
        className={buttonVariants({ size: "toolbar" })}
        data-testid="search-blocked-fix"
      >
        <Plus />
        {blocker.key === "indexer"
          ? t`Add an indexer to search`
          : t`Add a download client to search`}
      </Link>
    );
  }
  return (
    <Button
      type="button"
      size="toolbar"
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
    >
      <Search />
      {missing > 0 ? t`Search ${missing} wanted` : t`Search wanted`}
    </Button>
  );
}

function formatRouteReason(reason?: string | null): string {
  if (!reason) return t`No safe acquisition route is currently ready.`;
  return (
    ROUTE_REASON_COPY()[reason] ??
    t`Search is blocked: ${ph({ reason: reason.replace(/_/g, " ") })}.`
  );
}

function retainedLocations(raw?: string | null): string[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((folder): folder is string => typeof folder === "string")
      : [];
  } catch {
    return [];
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : t`Unable to load the search preview.`;
}

/** "Issue 12" / "Annual 3", or just the kind when there is no number. */
function issueFallbackLabel(issue: Issue, number?: string | null): string {
  if (!number) return issue.annual ? t`Annual` : t`Issue`;
  return issue.annual ? t`Annual ${number}` : t`Issue ${number}`;
}

const ISSUE_GRID_COLS =
  "grid-cols-[42px_minmax(0,1fr)_auto_36px] md:grid-cols-[28px_72px_42px_minmax(220px,1fr)_130px_110px_190px_36px]";

function issueRowKey(issue: Issue): string {
  return `${issue.annual ? "annual" : "issue"}:${issue.id ?? issue.IssueID}`;
}

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
  const name = issueName || issueFallbackLabel(issue, issueNumber);
  return t`Interactive Search for ${name}`;
}

/** "3 matched · 1 no match · 1 failed". */
function runCountsLine(run: {
  succeeded_count: number;
  no_match_count: number;
  failed_count?: number | null;
  blocked_count?: number | null;
}): string {
  const parts = [
    t`${ph({ count: run.succeeded_count })} matched`,
    t`${ph({ count: run.no_match_count })} no match`,
  ];
  if (run.failed_count)
    parts.push(t`${ph({ count: run.failed_count })} failed`);
  if (run.blocked_count)
    parts.push(t`${ph({ count: run.blocked_count })} blocked`);
  return parts.join(" · ");
}

export default function SeriesDetailPage() {
  const { comicId } = useParams<{ comicId: string }>();
  const navigate = useNavigate();
  const { addToast } = useToast();
  const [headerFits, setHeaderFits] = useState(false);
  // Compact bar: shown once the hero has scrolled out of the body scroller.
  // In the split layout the body never scrolls, so the hero stays put.
  const heroRef = useRef<HTMLDivElement>(null);
  const isMobile = useIsMobile();
  const [compact, setCompact] = useState(false);
  const onBodyScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
    const hero = heroRef.current;
    if (!hero) return;
    setCompact(event.currentTarget.scrollTop > hero.offsetHeight - 56);
  }, []);
  const observeBody = useCallback((body: HTMLDivElement | null) => {
    if (!body) return;
    const measure = () => {
      const headerHeight = Array.from(body.children).reduce((height, child) => {
        return child instanceof HTMLElement &&
          child.dataset.testid !== "series-issue-list"
          ? height + child.offsetHeight
          : height;
      }, 0);
      setHeaderFits(body.clientHeight - headerHeight >= 400);
    };
    const resizeObserver = new ResizeObserver(measure);
    const observeChildren = () => {
      resizeObserver.disconnect();
      resizeObserver.observe(body);
      for (const child of body.children) resizeObserver.observe(child);
      measure();
    };
    const mutationObserver = new MutationObserver(observeChildren);
    mutationObserver.observe(body, { childList: true });
    observeChildren();
    return () => {
      resizeObserver.disconnect();
      mutationObserver.disconnect();
    };
  }, []);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [filter, setFilter] = useState<IssueFilter>("all");
  const [tab, setTab] = useState<"issues" | "settings">("issues");
  const [searchDialogOpen, setSearchDialogOpen] = useState(false);
  const [preview, setPreview] = useState<SearchMissingPreview | null>(null);
  const [searchOutcome, setSearchOutcome] =
    useState<SearchMissingResult | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searchRunId, setSearchRunId] = useState<string | null>(null);
  const [selectedRows, setSelectedRows] = useState<Set<string>>(new Set());

  const {
    data: seriesData,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useSeriesDetail(comicId);
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
  const setIssueStatus = useSetIssueStatus();
  const bulkSetIssueStatus = useBulkSetIssueStatus();
  const { startReview, reviewSheetProps } = useInteractiveReview();
  const searchBlocker = useSearchBlockers().blockers[0];

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
        setSearchError(t`The search preview did not return a result.`);
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
        <h1 className="sr-only">
          <Trans>Series</Trans>
        </h1>
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

  if (error && !isNotFoundError(error)) {
    return (
      <div className="p-5">
        <ErrorDisplay
          error={error}
          title={t`Unable to load series`}
          onRetry={() => {
            void refetch();
          }}
          isRetrying={isFetching}
        />
      </div>
    );
  }

  if (!seriesData) {
    return (
      <div className="p-5">
        <div className="mx-auto max-w-lg py-16 text-center">
          <h1 className="text-lg font-semibold">
            <Trans>Series not found</Trans>
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {error?.message || t`Series not found.`}
          </p>
          <Link
            to="/library"
            className="mt-6 inline-block text-sm text-primary hover:underline"
          >
            <Trans>Back to library</Trans>
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
  const wanted =
    summary?.wantedMissing ?? allIssues.filter(isIssueWanted).length;
  const notWanted =
    summary?.notWanted ?? allIssues.filter(isIssueNotWanted).length;
  const reviewableMissing = summary?.eligible ?? wanted;
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
        title: t`Error`,
        description: t`Failed to update search settings`,
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
        title: t`Error`,
        description: t`Failed to update search settings`,
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
  const contentKind: SeriesKind = isManga
    ? "manga"
    : comic.ContentType?.toLowerCase() === "magazine"
      ? "magazine"
      : "comic";
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
      ? t`Volumes & chapters`
      : volumeCount
        ? t`Volumes`
        : chapterCount
          ? t`Chapters`
          : isManga
            ? t`Chapters`
            : t`Issues`;
  const hasArcs = allIssues.some((issue) => Boolean(issue.Arc));
  const ledgerFacets: string[] = [];
  if (volumeCount && chapterCount) {
    ledgerFacets.push(t`volumes: ${volumeCount}`, t`chapters: ${chapterCount}`);
  }
  if (annualCount) ledgerFacets.push(t`annuals: ${annualCount}`);
  // "grouped by arc" used to print unconditionally whenever there were no
  // annuals, including on a ledger whose every arc cell reads "—".
  if (hasArcs) ledgerFacets.push(t`grouped by arc`);
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
  const filteredIssues = allIssues.filter((issue) => {
    if (filter === "have") return isIssueOwned(issue);
    if (filter === "wanted") return isIssueWanted(issue);
    if (filter === "not_wanted") return isIssueNotWanted(issue);
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
        title: t`Error`,
        description: isPaused
          ? t`Failed to resume series`
          : t`Failed to pause series`,
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
        title: t`Error`,
        description: t`Failed to refresh series`,
      });
    }
  };

  const handleContentKindChange = async (nextKind: SeriesKind) => {
    if (!comicId || nextKind === contentKind) return;
    try {
      const result = await contentKindMutation.mutateAsync({
        comicId,
        contentType: nextKind,
      });
      addToast({
        type: "success",
        title: t`Content kind updated`,
        description: result.location_repointed
          ? t`This series is now cataloged as ${nextKind}. New downloads import under the ${nextKind} destination. Files already at the previous path were not moved.`
          : t`This series is now cataloged as ${nextKind}.`,
      });
    } catch {
      addToast({
        type: "error",
        title: t`Content kind not updated`,
        description: t`Comicarr could not save this classification. Try again.`,
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
        title: t`Error`,
        description: t`Failed to delete series`,
      });
    }
  };

  const toggleRowSelected = (key: string) => {
    if (bulkSetIssueStatus.isPending) return;
    setSelectedRows((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleAllFiltered = (checked: boolean) => {
    if (bulkSetIssueStatus.isPending) return;
    setSelectedRows((current) => {
      const next = new Set(current);
      for (const issue of filteredIssues) {
        if (checked) next.add(issueRowKey(issue));
        else next.delete(issueRowKey(issue));
      }
      return next;
    });
  };

  const selectedTargets = allIssues
    .filter((issue) => selectedRows.has(issueRowKey(issue)))
    .map((issue) => ({
      issueId: String(issue.id ?? issue.IssueID),
      annual: Boolean(issue.annual),
    }));
  const visibleKeys = filteredIssues.map(issueRowKey);
  const allFilteredSelected =
    visibleKeys.length > 0 && visibleKeys.every((key) => selectedRows.has(key));
  const someFilteredSelected = visibleKeys.some((key) => selectedRows.has(key));

  const handleIssueStatusSelect = (
    issue: Issue,
    status: SettableIssueStatus,
  ) => {
    const issueId = issue.id ?? issue.IssueID;
    if (!issueId || bulkSetIssueStatus.isPending) return;
    setIssueStatus.mutate(
      { issueId: String(issueId), annual: Boolean(issue.annual), status },
      {
        onError: (statusError) =>
          addToast({
            type: "error",
            title: t`Error`,
            description: t`Failed to update status: ${ph({ message: statusError.message })}`,
          }),
      },
    );
  };

  const handleBulkSetStatus = async (status: SettableIssueStatus) => {
    if (
      bulkSetIssueStatus.isPending ||
      setIssueStatus.isPending ||
      selectedTargets.length === 0
    )
      return;
    try {
      const { type, message, keep } = describeBulkResult(
        await bulkSetIssueStatus.mutateAsync({
          targets: selectedTargets,
          status,
        }),
        `mark-${status.toLowerCase() as Lowercase<SettableIssueStatus>}`,
      );
      addToast({ type, message });
      setSelectedRows(new Set(keep));
    } catch (bulkError) {
      addToast({
        type: "error",
        title: t`Error`,
        description:
          bulkError instanceof Error
            ? t`Failed to update statuses: ${ph({ error: bulkError.message })}`
            : t`Failed to update statuses: Unknown error`,
      });
    }
  };

  const segments = [
    { key: "have", value: have, color: "var(--status-downloaded)" },
    { key: "in-flight", value: inFlight, color: "var(--in-flight)" },
    { key: "wanted", value: wanted, color: "var(--status-wanted)" },
    {
      key: "rest",
      value: Math.max(0, total - have - inFlight - wanted),
      color: "var(--surface-3)",
    },
  ].filter((segment) => segment.value > 0);
  const progressSummary = [
    wanted > 0 ? t`${wanted} wanted` : null,
    inFlight > 0 ? t`${inFlight} in progress` : null,
  ]
    .filter(Boolean)
    .join(", ");
  const statusTone = isPaused
    ? "var(--status-paused)"
    : comic.Status?.toLowerCase() === "ended"
      ? "var(--status-ended)"
      : "var(--status-active)";
  const statusWord = isPaused
    ? t`Paused`
    : comic.Status?.toLowerCase() === "ended"
      ? t`Ended`
      : t`Continuing`;

  const startMissingReview = (unfiltered: boolean) => {
    if (!comicId) return;
    void startReview(
      {
        ComicName: comic.ComicName,
        Status: comic.Status,
        scope: "series",
        missingCount: reviewableMissing,
        ...(unfiltered ? { unfiltered: true } : {}),
      },
      {
        entityType: "series",
        entityId: String(comicId),
        ...(unfiltered ? { mode: "unfiltered" as const } : {}),
      },
    );
  };
  const reviewDisabled =
    !comicId || reviewableMissing === 0 || reviewSheetProps.startPending;

  return (
    <div className="relative flex h-full min-h-0 min-w-0 flex-col page-transition">
      {compact && (
        <div
          data-testid="series-compact-bar"
          className="absolute inset-x-0 top-0 z-20 flex h-14 items-center gap-3 border-b border-border-subtle bg-background/95 px-8 backdrop-blur"
        >
          <div className="h-8 w-6 shrink-0 overflow-hidden rounded-sm bg-surface-2">
            {coverSrc && (
              <img
                src={coverSrc}
                alt=""
                className="h-full w-full object-cover"
                onError={(event) => {
                  event.currentTarget.style.display = "none";
                }}
              />
            )}
          </div>
          <span className="truncate text-[15px] font-semibold">
            {comic.ComicName}
          </span>
          <span className="hidden shrink-0 rounded-md border border-border-strong px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.04em] text-muted-foreground sm:inline">
            {isManga ? t`Manga` : t`Comic`}
          </span>
          <div
            aria-hidden="true"
            className="ml-3 hidden h-1 w-[120px] shrink-0 gap-0.5 overflow-hidden rounded-full md:flex"
          >
            {segments.length === 0 ? (
              <div className="flex-1 bg-surface-3" />
            ) : (
              segments.map((segment) => (
                <div
                  key={segment.key}
                  style={{ flexGrow: segment.value, background: segment.color }}
                />
              ))
            )}
          </div>
          <span className="hidden shrink-0 font-mono text-xs text-foreground md:inline">
            {have} / {total}
          </span>
          {wanted > 0 && (
            <span className="hidden shrink-0 text-[13px] text-foreground-2 lg:inline">
              <Trans>{wanted} wanted</Trans>
            </span>
          )}
          <div className="ml-auto flex shrink-0 items-center gap-2">
            <SearchMissingButton
              blocker={searchBlocker}
              missing={wanted}
              onClick={handleOpenSearch}
              disabled={!comicId || searchPreview.isFetching}
            />
            <Button
              type="button"
              variant="outline"
              size="toolbar"
              className="hidden bg-surface-2 sm:inline-flex"
              onClick={handleRefresh}
              disabled={refreshMutation.isPending}
              aria-label={t`Refresh series`}
            >
              <RefreshCw
                className={refreshMutation.isPending ? "animate-spin" : ""}
              />
              <Trans>Refresh</Trans>
            </Button>
          </div>
        </div>
      )}
      {/*
        Full-bleed Layout clips this page. On narrow or short viewports
        (phones in either orientation) the hero can be taller than the
        leftover height, so the issue list shares this overflow-y-auto
        instead of living in a sibling that collapses to 0. The split
        variant (wide and tall, see index.css) locks the hero and makes the
        table the inner scroller.
      */}
      <div
        ref={observeBody}
        onScroll={onBodyScroll}
        className={`min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden ${headerFits ? "split:flex split:flex-col split:overflow-hidden" : ""}`}
        data-testid="series-body-scroll"
      >
        <div ref={heroRef} className="relative shrink-0 overflow-hidden">
          {/* Blurred cover wash: the series' own colors, kept faint. */}
          {coverSrc && (
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 top-0 h-[300px] opacity-[0.16] dark:opacity-25"
              style={{
                backgroundImage: `url(${coverSrc})`,
                backgroundSize: "cover",
                backgroundPosition: "center 30%",
                filter: "blur(48px) saturate(1.2)",
                maskImage: "linear-gradient(to bottom, black, transparent)",
              }}
            />
          )}

          <div className="relative px-4 pt-4 md:px-8 md:pt-5">
            <nav
              aria-label={t`Breadcrumb`}
              className="mb-4 flex items-center gap-2 text-[13px] text-foreground-2 md:mb-5"
            >
              <Link
                to="/library"
                className="inline-flex items-center gap-1 hover:text-foreground max-md:text-[15px]"
              >
                <ChevronLeft
                  className="size-5 -ml-1 md:hidden"
                  aria-hidden="true"
                />
                <Trans>Library</Trans>
              </Link>
              <span className="text-muted-foreground max-md:hidden">/</span>
              <span className="truncate text-foreground max-md:hidden">
                {comic.ComicName}
              </span>
              <span className="mono-meta ml-auto hidden shrink-0 sm:inline">
                {providerCode}:{comic.ComicID} · {seriesSyncLabel(comic)}
              </span>
            </nav>

            <div className="grid grid-cols-[96px_minmax(0,1fr)] items-end gap-4 md:flex md:flex-row md:items-start md:gap-5">
              <div className="aspect-[2/3] w-24 shrink-0 overflow-hidden rounded-md bg-surface-2 shadow-sm">
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

              <div className="min-w-0 flex-1 pt-1">
                <div className="flex flex-wrap items-center gap-2.5">
                  <h1 className="text-[22px] font-semibold leading-tight tracking-[-0.02em] md:text-[28px]">
                    {comic.ComicName}
                  </h1>
                  <span className="rounded-md border border-border-strong px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">
                    {isManga ? t`Manga` : t`Comic`}
                  </span>
                </div>

                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-foreground-2">
                  <span className="inline-flex items-center gap-1.5">
                    <span
                      className="size-1.5 rounded-full"
                      style={{ background: statusTone }}
                      aria-hidden="true"
                    />
                    {statusWord}
                  </span>
                  {(comic.ComicPublisher || comic.ComicYear) && (
                    <span>
                      {[comic.ComicPublisher, comic.ComicYear]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  )}
                  <span className="font-mono text-xs text-foreground">
                    {have} / {total}
                  </span>
                  {progressSummary && <span>{progressSummary}</span>}
                </div>

                {comic.Description && !isMobile && (
                  <p
                    className="mt-2 max-h-40 max-w-[640px] overflow-y-auto text-[13px] leading-relaxed text-foreground-2"
                    data-testid="series-description"
                  >
                    {comic.Description}
                  </p>
                )}

                {seriesData.providerLinks &&
                seriesData.providerLinks.length > 0 ? (
                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                    {seriesData.providerLinks.map((link) => (
                      <a
                        key={`${link.provider}-${link.url}`}
                        href={link.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-[12px] text-foreground-2 hover:text-foreground hover:underline"
                      >
                        {t`View on ${ph({ site: link.label })}`}
                        <ExternalLink className="h-3 w-3" aria-hidden="true" />
                      </a>
                    ))}
                  </div>
                ) : null}
              </div>

              {comic.Description && isMobile && (
                <p className="col-span-2 line-clamp-3 text-[13px] leading-relaxed text-foreground-2">
                  {comic.Description}
                </p>
              )}
              <div className="col-span-2 flex shrink-0 flex-wrap items-center gap-2 md:pt-12">
                {!showDeleteConfirm ? (
                  <>
                    <SearchMissingButton
                      blocker={searchBlocker}
                      missing={wanted}
                      onClick={handleOpenSearch}
                      disabled={!comicId || searchPreview.isFetching}
                      aria-label={t`Search all missing`}
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="toolbar"
                      className="bg-surface-2"
                      onClick={handleRefresh}
                      disabled={refreshMutation.isPending}
                    >
                      <RefreshCw
                        className={
                          refreshMutation.isPending ? "animate-spin" : ""
                        }
                      />
                      <Trans>Refresh</Trans>
                    </Button>
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        render={
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            aria-label={t`More series actions`}
                          >
                            <MoreHorizontal />
                          </Button>
                        }
                      />
                      <DropdownMenuContent align="end" className="min-w-52">
                        <DropdownMenuItem
                          disabled={reviewDisabled}
                          onClick={() => startMissingReview(false)}
                          aria-label={t`Interactive Search for missing issues`}
                        >
                          <Search />
                          <Trans>Review missing</Trans>
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          disabled={reviewDisabled}
                          onClick={() => startMissingReview(true)}
                          aria-label={t`Browse every indexer's releases for this series`}
                        >
                          <TextSearch />
                          <Trans>Browse releases</Trans>
                        </DropdownMenuItem>
                        {comicId ? (
                          <DropdownMenuItem
                            render={
                              <Link
                                to={`/activity?scope_type=series&scope_id=${encodeURIComponent(comicId)}`}
                              />
                            }
                            aria-label={t`View activity for this series`}
                          >
                            <Activity />
                            <Trans>Activity</Trans>
                          </DropdownMenuItem>
                        ) : null}
                        <DropdownMenuItem
                          disabled={
                            pauseMutation.isPending || resumeMutation.isPending
                          }
                          onClick={() => void handlePauseResume()}
                        >
                          {isPaused ? <Play /> : <Pause />}
                          {isPaused ? t`Resume` : t`Pause`}
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          onClick={() => setShowDeleteConfirm(true)}
                          className="text-[var(--status-error)]"
                        >
                          <Trash2 />
                          <Trans>Delete</Trans>
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </>
                ) : (
                  <>
                    <span className="text-[13px] text-foreground-2">
                      <Trans>Delete this series?</Trans>
                    </span>
                    <Button
                      type="button"
                      variant="destructive"
                      size="toolbar"
                      onClick={handleDelete}
                      disabled={deleteMutation.isPending}
                      className="font-semibold"
                    >
                      <Trash2 />
                      <Trans>Confirm delete</Trans>
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="toolbar"
                      onClick={() => setShowDeleteConfirm(false)}
                    >
                      <Trans>Cancel</Trans>
                    </Button>
                  </>
                )}
              </div>
            </div>

            {/* Owned, in progress, the rest: one bar, no percentage score. */}
            <div
              className="mt-5 flex h-1 gap-0.5 overflow-hidden rounded-full"
              role="img"
              aria-label={
                progressSummary
                  ? t`${completionPct}% held: ${have} of ${total}, ${progressSummary}`
                  : t`${completionPct}% held: ${have} of ${total}`
              }
            >
              {segments.length === 0 ? (
                <div className="flex-1 bg-surface-3" />
              ) : (
                segments.map((segment) => (
                  <div
                    key={segment.key}
                    style={{
                      flexGrow: segment.value,
                      background: segment.color,
                    }}
                  />
                ))
              )}
            </div>
          </div>

          <div className="relative mt-4">
            <TabRow ariaLabel={t`Series sections`}>
              <Tab
                active={tab === "issues"}
                label={ledgerLabel}
                meta={total}
                onClick={() => setTab("issues")}
              />
              <Tab
                active={tab === "settings"}
                label={t`Settings`}
                onClick={() => setTab("settings")}
              />
            </TabRow>
          </div>
        </div>

        {tab === "issues" ? (
          <>
            <div className="flex shrink-0 flex-wrap items-center gap-3 px-8 py-3">
              <div className="sr-only" data-testid="ledger-label">
                {ledgerLabel}
              </div>
              <div
                role="group"
                aria-label={t`Filter issues`}
                className={SEGMENTED_GROUP}
              >
                {(
                  [
                    ["all", t`All`, total],
                    ["have", t`Have`, have],
                    ["wanted", t`Wanted`, wanted],
                    ["not_wanted", t`Not wanted`, notWanted],
                  ] as const
                ).map(([key, label, count]) => (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={filter === key}
                    aria-label={`${label} ${count}`}
                    onClick={() => setFilter(key)}
                    className={SEGMENTED_ITEM}
                  >
                    {label}
                    <span className="mono-meta">{count}</span>
                  </button>
                ))}
              </div>
              <div className="mono-meta ml-auto" data-testid="ledger-facets">
                {ledgerFacets.length
                  ? `${total} · ${ledgerFacets.join(" · ")}`
                  : total}
              </div>
            </div>

            {selectedTargets.length > 0 && (
              <div className="mx-8 mb-2 flex shrink-0 flex-wrap items-center gap-3 rounded-md border border-border-subtle bg-surface-1 px-3 py-1.5">
                <span
                  className="mono-label"
                  data-testid="issue-selection-count"
                >
                  {plural(selectedTargets.length, {
                    one: "# selected",
                    other: "# selected",
                  })}
                </span>
                <IssueStatusMenu
                  disabled={
                    bulkSetIssueStatus.isPending || setIssueStatus.isPending
                  }
                  trigger={
                    <Button
                      type="button"
                      variant="outline"
                      size="toolbar"
                      aria-label={t`Set status on selected issues`}
                    >
                      <Trans>Set status</Trans>
                      <ChevronDown aria-hidden="true" />
                    </Button>
                  }
                  onSelect={(status) => void handleBulkSetStatus(status)}
                />
                <button
                  type="button"
                  onClick={() => setSelectedRows(new Set())}
                  disabled={bulkSetIssueStatus.isPending}
                  className="mono-label transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <Trans>Clear</Trans>
                </button>
              </div>
            )}

            <div
              className={`min-w-0 md:overflow-x-auto ${headerFits ? "split:min-h-0 split:flex-1 split:overflow-auto" : ""}`}
              data-testid="series-issue-list"
            >
              <div className="md:min-w-[920px]">
                <div
                  className={`sticky top-0 z-10 grid ${ISSUE_GRID_COLS} h-8 items-center gap-3 border-b border-border-subtle bg-background mx-8 px-2 text-[11px] font-semibold uppercase tracking-[0.04em] text-muted-foreground`}
                >
                  <div className={`${DESKTOP_COL} flex items-center`}>
                    <Checkbox
                      checked={
                        allFilteredSelected
                          ? true
                          : someFilteredSelected
                            ? "indeterminate"
                            : false
                      }
                      onCheckedChange={toggleAllFiltered}
                      aria-label={t`Select all visible issues`}
                      disabled={bulkSetIssueStatus.isPending}
                    />
                  </div>
                  <div className={DESKTOP_COL}>
                    <Trans>type</Trans>
                  </div>
                  <div>#</div>
                  <div>
                    <Trans>title</Trans>
                  </div>
                  <div className={DESKTOP_COL}>
                    <Trans>arc</Trans>
                  </div>
                  <div className={DESKTOP_COL}>
                    <Trans>date</Trans>
                  </div>
                  <div>
                    <Trans>state</Trans>
                  </div>
                  <div className="sr-only">
                    <Trans>search</Trans>
                  </div>
                </div>

                {filteredIssues.length === 0 ? (
                  <div
                    className="px-5 py-8 text-center font-mono text-[11px]"
                    style={{ color: "var(--muted-foreground)" }}
                  >
                    <Trans>no issues to display</Trans>
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
                    const status = issueLabel(issue);
                    const separateIntent = getSeparateIntent(issue);
                    const ledgerKind = getLedgerKind(issue, isManga);
                    const rowKey = issueRowKey(issue);
                    const rowLabel =
                      issueName || issueFallbackLabel(issue, issueNumber);
                    return (
                      <div
                        key={`${issue.annual ? "annual" : "issue"}-${issueId}`}
                        className={`group/row grid ${ISSUE_GRID_COLS} min-h-9 items-center gap-3 border-b border-border-subtle mx-8 px-2 py-1 text-[13px] transition-colors hover:bg-surface-1`}
                      >
                        <div className={`${DESKTOP_COL} flex items-center`}>
                          <Checkbox
                            checked={selectedRows.has(rowKey)}
                            onCheckedChange={() => toggleRowSelected(rowKey)}
                            aria-label={t`Select ${rowLabel}`}
                            disabled={!issueId || bulkSetIssueStatus.isPending}
                          />
                        </div>
                        <div className={DESKTOP_COL}>
                          {ledgerKind && (
                            <span className="rounded-md border border-border-strong px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">
                              {LEDGER_KIND_LABEL()[ledgerKind]}
                            </span>
                          )}
                        </div>
                        <div
                          className="font-mono"
                          style={{ color: "var(--muted-foreground)" }}
                        >
                          #{String(issueNumber ?? "").padStart(2, "0")}
                        </div>
                        <div className="min-w-0 truncate" data-grid-title="">
                          {ledgerKind ? (
                            <span
                              data-testid="phone-row-id"
                              className="mr-1.5 hidden max-md:inline rounded-md border border-border-strong px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.04em] text-muted-foreground"
                            >
                              {LEDGER_KIND_LABEL()[ledgerKind]}
                            </span>
                          ) : null}
                          <Link
                            to={`/library/${comicId}/issue/${issueId}`}
                            className="underline-offset-2 hover:underline"
                          >
                            {issueName ||
                              issueFallbackLabel(issue, issueNumber)}
                          </Link>
                        </div>
                        <div
                          className={`${DESKTOP_COL} truncate text-[11px]`}
                          style={{ color: "var(--muted-foreground)" }}
                        >
                          {issue.Arc || "—"}
                        </div>
                        <div
                          className={`${DESKTOP_COL} font-mono text-[10px]`}
                          style={{ color: "var(--muted-foreground)" }}
                        >
                          {displayComicDate(issueDate)}
                        </div>
                        <div
                          className="flex min-w-0 flex-wrap items-center gap-1.5"
                          data-grid-status=""
                        >
                          <IssueStatusMenu
                            current={status}
                            label={t`Change status for ${rowLabel}`}
                            disabled={
                              !issueId ||
                              setIssueStatus.isPending ||
                              bulkSetIssueStatus.isPending
                            }
                            onSelect={(next) =>
                              handleIssueStatusSelect(issue, next)
                            }
                          />
                          {isIssueNotWanted(issue) && issueId && (
                            <button
                              type="button"
                              className="rounded-control px-1.5 text-[12px] text-foreground-2 underline-offset-2 opacity-0 transition-opacity hover:text-foreground hover:underline focus-visible:opacity-100 group-hover/row:opacity-100 max-md:opacity-100"
                              aria-label={t`Want ${rowLabel}`}
                              disabled={
                                setIssueStatus.isPending ||
                                bulkSetIssueStatus.isPending
                              }
                              onClick={() =>
                                handleIssueStatusSelect(issue, "Wanted")
                              }
                            >
                              <Trans>Want</Trans>
                            </button>
                          )}
                          {separateIntent && (
                            <span
                              className="font-mono text-[9px] lowercase"
                              style={{ color: "var(--muted-foreground)" }}
                            >
                              <Trans>intent: {separateIntent}</Trans>
                            </span>
                          )}
                        </div>
                        <div className="flex justify-end">
                          {!searchBlocker && (
                            <button
                              type="button"
                              className="inline-flex size-7 items-center justify-center rounded-control transition-colors hover:bg-secondary/50"
                              style={{ color: "var(--muted-foreground)" }}
                              aria-label={interactiveSearchLabel(issue)}
                              title={t`Interactive Search`}
                              disabled={!issueId}
                              onClick={() =>
                                void startReview(
                                  toReleaseReviewIssue(issue, comic.ComicName),
                                  {
                                    entityType: issue.annual
                                      ? "annual"
                                      : "issue",
                                    entityId: String(issueId ?? ""),
                                  },
                                )
                              }
                            >
                              <Search
                                className="h-3.5 w-3.5"
                                aria-hidden="true"
                              />
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </>
        ) : (
          <div
            className="grid max-w-[720px] gap-4 px-8 py-6"
            data-testid="series-settings"
          >
            <section>
              <SeriesContentKind
                value={contentKind}
                provider={provider}
                pending={contentKindMutation.isPending}
                onChange={(nextKind) => void handleContentKindChange(nextKind)}
              />
            </section>
            {comicId ? (
              <section>
                <SeriesFolder
                  comicId={comicId}
                  location={comic.ComicLocation}
                  override={comic.LocationOverride === 1}
                  retained={retainedLocations(comic.RetainedLocations)}
                />
              </section>
            ) : null}
            {comicId && seriesData.searchProviders ? (
              <section>
                <SeriesSearchProviders
                  comicId={comicId}
                  available={seriesData.searchProviders.available}
                  override={seriesData.searchProviders.override}
                />
              </section>
            ) : null}
            <section className="rounded-lg border border-border-subtle bg-surface-1 px-4 py-3">
              <h2 className="mb-1 text-[13px] font-semibold">
                <Trans>Matching</Trans>
              </h2>
              {[
                {
                  key: "allowPacks" as const,
                  label: t`Allow packs`,
                  title: t`Accept pack/bundle releases (multi-issue or volume torrents) when searching`,
                  checked: allowPacks,
                },
                {
                  key: "ignoreType" as const,
                  label: t`Ignore book type`,
                  title: t`Match results even when the release's book type (TPB, GN…) differs from this series`,
                  checked: ignoreType,
                },
              ].map(({ key, label, title, checked }) => (
                <label
                  key={key}
                  title={title}
                  className="flex cursor-pointer items-center justify-between gap-2 py-1.5 text-sm"
                >
                  <span className="text-foreground">{label}</span>
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
                  <label className="grid gap-1 text-sm">
                    <span style={{ color: "var(--muted-foreground)" }}>
                      <Trans>Bare numbers</Trans>
                    </span>
                    <select
                      aria-label={t`Bare numbers`}
                      className="h-8 rounded-control border border-border-strong bg-surface-2 px-2"
                      disabled={searchSettingsMutation.isPending}
                      value={comic.BareNumberMode || "auto"}
                      onChange={(event) =>
                        void handleMangaModeChange(
                          "bareNumberMode",
                          event.target.value,
                        )
                      }
                    >
                      <option value="auto">
                        <Trans>Auto</Trans>
                      </option>
                      <option value="volumes">
                        <Trans>Volumes</Trans>
                      </option>
                      <option value="chapters">
                        <Trans>Chapters</Trans>
                      </option>
                    </select>
                  </label>
                  <label className="grid gap-1 text-sm">
                    <span style={{ color: "var(--muted-foreground)" }}>
                      <Trans>Monitor</Trans>
                    </span>
                    <select
                      aria-label={t`Monitor`}
                      className="h-8 rounded-control border border-border-strong bg-surface-2 px-2"
                      disabled={searchSettingsMutation.isPending}
                      value={comic.MonitorMode || "blended"}
                      onChange={(event) =>
                        void handleMangaModeChange(
                          "monitorMode",
                          event.target.value,
                        )
                      }
                    >
                      <option value="blended">
                        <Trans>Blended frontier</Trans>
                      </option>
                      <option value="volumes">
                        <Trans>Volumes only</Trans>
                      </option>
                      <option value="chapters">
                        <Trans>Chapters only</Trans>
                      </option>
                    </select>
                  </label>
                </div>
              ) : null}
            </section>
          </div>
        )}
      </div>

      <Dialog open={searchDialogOpen} onOpenChange={handleSearchDialogChange}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>
              <Trans>Search missing issues</Trans>
            </DialogTitle>
            <DialogDescription>
              <Trans>
                Review the current selection before Comicarr creates one durable
                search run.
              </Trans>
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
              <Callout tone="error" className="p-3 text-[12px]">
                <div className="font-semibold">
                  <Trans>Unable to confirm this search</Trans>
                </div>
                <div className="mt-1">{searchError}</div>
              </Callout>
            )}

            {preview && !searchOutcome && !searchPreview.isFetching && (
              <>
                <div
                  className="rounded-control border p-3 text-[12px]"
                  style={{
                    borderColor: "var(--border)",
                    background: "var(--card)",
                  }}
                >
                  <div className="font-semibold">
                    {plural(preview.eligibleCount, {
                      one: "# eligible issue will be searched.",
                      other: "# eligible issues will be searched.",
                    })}
                  </div>
                  <div
                    className="mt-1"
                    style={{ color: "var(--muted-foreground)" }}
                  >
                    {plural(preview.excludedCount, {
                      one: "# issue is excluded from this run.",
                      other: "# issues are excluded from this run.",
                    })}
                  </div>
                  {preview.eligible?.some(
                    (item) => item.entityType === "annual",
                  ) && (
                    <div
                      className="mt-2 font-mono text-[10px]"
                      style={{ color: "var(--primary)" }}
                    >
                      <Trans>Includes annuals when they are eligible.</Trans>
                    </div>
                  )}
                </div>

                {!routeViable ? (
                  <Callout tone="warning" className="p-3 text-[12px]">
                    <div className="font-semibold">
                      <Trans>Search configuration needs attention</Trans>
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
                        style={{ color: "var(--muted-foreground)" }}
                      >
                        {preview.route.reason}
                      </div>
                    )}
                    {preview.route?.reason &&
                      ROUTE_REASON_FIX()[preview.route.reason] && (
                        <Button
                          asChild
                          variant="outline"
                          size="sm"
                          className="mt-3"
                        >
                          <Link
                            to={ROUTE_REASON_FIX()[preview.route.reason].to}
                          >
                            {ROUTE_REASON_FIX()[preview.route.reason].label}
                          </Link>
                        </Button>
                      )}
                  </Callout>
                ) : preview.eligibleCount === 0 ? (
                  <div
                    className="rounded-control border p-3 text-[12px]"
                    style={{
                      borderColor: "var(--border)",
                      color: "var(--muted-foreground)",
                    }}
                  >
                    <Trans>No eligible missing issues remain to search.</Trans>
                  </div>
                ) : (
                  <p
                    className="text-[12px]"
                    style={{ color: "var(--muted-foreground)" }}
                  >
                    <Trans>
                      Confirmation queues this exact preview once. The run owns
                      retries and outcome tracking.
                    </Trans>
                  </p>
                )}
              </>
            )}

            {searchOutcome && (
              <div
                className="rounded-control border p-3 text-[12px]"
                style={{
                  borderColor: "var(--border)",
                  background: "var(--card)",
                }}
              >
                <div className="font-semibold">
                  {searchOutcome.run_id
                    ? t`Search run accepted`
                    : t`Search result`}
                </div>
                <div
                  className="mt-1"
                  style={{ color: "var(--muted-foreground)" }}
                >
                  {searchOutcome.message ||
                    (searchOutcome.status === "noop"
                      ? t`No eligible missing issues remain to search.`
                      : t`The search request was recorded.`)}
                </div>
                {run && (
                  <div
                    className="mt-3 rounded-md border px-2.5 py-2 font-mono text-[10px]"
                    style={{ borderColor: "var(--border)" }}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span style={{ color: "var(--muted-foreground)" }}>
                        <Trans>run state</Trans>
                      </span>
                      <span>{run.completion_state}</span>
                    </div>
                    <div
                      className="mt-1"
                      style={{ color: "var(--muted-foreground)" }}
                    >
                      {runCountsLine(run)}
                    </div>
                  </div>
                )}
                {searchRun.isLoading && (
                  <div
                    className="mt-3 font-mono text-[10px]"
                    style={{ color: "var(--muted-foreground)" }}
                  >
                    <Trans>Checking run outcome…</Trans>
                  </div>
                )}
                {searchRun.isError && (
                  <div
                    role="alert"
                    className="mt-3"
                    style={{ color: "var(--status-error)" }}
                  >
                    <Trans>
                      Unable to refresh the run outcome. It remains recorded and
                      can be checked from Activity.
                    </Trans>
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
                      ? t`Retrying queue handoff…`
                      : t`Retry queue handoff`}
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
              {searchOutcome ? t`Close` : t`Cancel`}
            </Button>
            {!searchOutcome && (searchError || !routeViable) && (
              <Button
                type="button"
                variant="outline"
                onClick={() => void fetchSearchPreview()}
                disabled={searchPreview.isFetching}
              >
                <Trans>Refresh preview</Trans>
              </Button>
            )}
            {!searchOutcome && preview && (
              <Button
                type="button"
                onClick={() => void handleConfirmSearch()}
                disabled={!canConfirm || confirmSearch.isPending}
              >
                {confirmSearch.isPending ? t`Confirming…` : t`Confirm search`}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ReleaseReviewSheet {...reviewSheetProps} />
    </div>
  );
}
