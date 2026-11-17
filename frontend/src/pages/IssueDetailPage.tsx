import { ph, plural, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { formatBytes, formatNumber } from "@/lib/intl";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { Activity, LibraryBig, Search, Star } from "lucide-react";
import IssueStatusMenu from "@/components/series/IssueStatusMenu";
import { SectionHeader } from "@/components/dashboard/DashboardPanel";
import { ShelfSheet } from "@/components/shelf/ShelfSheet";
import { Button, buttonVariants } from "@/components/ui/button";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { useIssueDetail } from "@/hooks/useIssueDetail";
import { useActivityBand } from "@/hooks/useActivity";
import {
  useIssueStoryDetails,
  type IssueStoryDetails,
  type SearchCandidate,
} from "@/hooks/useIssueStoryDetails";
import { useState } from "react";
import IssueStory, { IssueCauseActions } from "@/components/series/IssueStory";
import { useSetIssueStatus } from "@/hooks/useSeries";
import { useSearchWantedIssue } from "@/hooks/useQueue";
import { getErrorMessage } from "@/lib/api";
import { useSeriesShelf, useShelfEnabled } from "@/hooks/useShelf";
import type { IssueMetadata } from "@/hooks/useIssueDetail";
import { isNotFoundError } from "@/lib/api";

function issueNumber(issue: IssueMetadata): string {
  return String(issue.Issue_Number ?? issue.number ?? "").trim();
}

/** The issue's own title, unless it only restates its number. */
function issueName(issue: IssueMetadata): string {
  const name = String(issue.IssueName ?? issue.name ?? "").trim();
  const number = issueNumber(issue);
  if (!name || (number && /^(issue|chapter|ch\.?)?\s*#?\s*[\d.]+$/i.test(name)))
    return "";
  return name;
}

function issueStatus(issue: IssueMetadata): string {
  return issue.displayState ?? issue.status ?? issue.Status ?? t`Unknown`;
}

/** "26-Oct-2026 14:09:02 - INFO :: postprocess : msg" → "14:09:02 postprocess: msg". */
function shortLogLine(line: string): string {
  const match = line.match(
    /^\d{2}-[A-Za-z]{3}-\d{4} (\d{2}:\d{2}:\d{2}) - [A-Z]+\s*:: (.*)$/,
  );
  if (!match) return line;
  const [, time, rest] = match;
  const body = rest.replace(/^([\w.-]+) : /, "$1: ");
  return `${time} ${body}`;
}

function megabytes(bytes: number | null): string {
  if (bytes == null || !Number.isFinite(bytes)) return "";
  const mb = formatNumber(Math.round(bytes / 1_000_000));
  return t`${mb} MB`;
}

function attemptsLine(attempts: IssueStoryDetails["attempts"]): string {
  const parts: string[] = [];
  if (attempts.search > 0)
    parts.push(
      plural(attempts.search, { one: "# search", other: "# searches" }),
    );
  if (attempts.download > 0)
    parts.push(
      plural(attempts.download, { one: "# download", other: "# downloads" }),
    );
  if (attempts.import > 0)
    parts.push(
      plural(attempts.import, { one: "# import", other: "# imports" }),
    );
  return parts.length ? parts.join(" · ") : t`none yet`;
}

function CandidateRow({ row }: { row: SearchCandidate }) {
  const accepted = row.status === "accepted";
  return (
    <li
      data-testid="issue-candidate"
      className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-baseline gap-x-3 py-1 text-[13px]"
    >
      <span
        className="min-w-0 truncate font-mono text-xs text-foreground"
        title={`${row.title} · ${row.provider}`}
      >
        {row.title}
      </span>
      <span className="font-mono text-xs whitespace-nowrap text-muted-foreground">
        {megabytes(row.size_bytes)}
      </span>
      <span className="flex items-center gap-1.5 whitespace-nowrap text-foreground-2">
        <span
          aria-hidden="true"
          className="size-1.5 rounded-full"
          style={{
            background: row.chosen
              ? "var(--status-downloaded)"
              : accepted
                ? "var(--text-muted)"
                : "var(--status-error)",
          }}
        />
        {row.chosen
          ? t`Chosen`
          : accepted
            ? t`Acceptable`
            : (row.reason ?? t`Rejected`)}
      </span>
    </li>
  );
}

function Candidates({ details }: { details: IssueStoryDetails }) {
  const [showRejected, setShowRejected] = useState(false);
  const search = details.search;
  if (!search) return null;
  return (
    <div className="mt-6" data-testid="issue-candidates">
      <SectionHeader
        title={t`Candidates · ${ph({ accepted_count: search.accepted_count })} of ${ph({ total: search.total })}`}
      />
      {search.total === 0 ? (
        <p className="text-[13px] text-foreground-2">
          <Trans>The last search found nothing for this issue.</Trans>
        </p>
      ) : (
        <ul>
          {search.accepted.map((row, index) => (
            <CandidateRow key={`a-${index}`} row={row} />
          ))}
          {showRejected &&
            search.rejected.map((row, index) => (
              <CandidateRow key={`r-${index}`} row={row} />
            ))}
        </ul>
      )}
      {search.rejected_count > 0 && (
        <button
          type="button"
          className="mt-1 text-[13px] text-foreground-2 hover:text-foreground"
          onClick={() => setShowRejected((open) => !open)}
        >
          {showRejected
            ? t`Hide rejected`
            : t`Show ${ph({ rejected_count: search.rejected_count })} rejected`}
        </button>
      )}
      {showRejected && search.rejected_count > search.rejected.length && (
        <p className="mt-1 text-xs text-muted-foreground">
          {t`Showing the first ${ph({ count: search.rejected.length })}.`}
        </p>
      )}
    </div>
  );
}

/** "12.3 MB" for a byte count, the stored text otherwise. */
function sizeLabel(value: string | number | null | undefined): string | null {
  if (value === null || value === undefined || value === "") return null;
  const bytes = Number(value);
  return Number.isFinite(bytes) && bytes > 0
    ? formatBytes(bytes)
    : String(value);
}

/** Issue states with nothing on disk that a search can still fix. */
function searchable(status: string): boolean {
  return status === "Wanted" || status === "Failed";
}
/** Issue states a user usually means to want when they open the page. */
function wantable(status: string): boolean {
  return status === "Skipped" || status === "Ignored";
}

function field(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

export default function IssueDetailPage() {
  const { comicId, issueId } = useParams<{
    comicId: string;
    issueId: string;
  }>();
  const { data, isLoading, error, isError, refetch, isFetching } =
    useIssueDetail(comicId, issueId);
  const setIssueStatus = useSetIssueStatus();
  const searchIssue = useSearchWantedIssue();
  const { addToast } = useToast();
  const band = useActivityBand(
    issueId ? { scope_type: "issue", scope_id: issueId } : {},
  );
  const cause = issueId ? (band.data?.causes?.[0] ?? null) : null;
  const story = useIssueStoryDetails(issueId);
  // Print copies hang off issues. A manga series keeps them on its volumes.
  const shelfEnabled = useShelfEnabled() && !/^(md|mal)-/.test(comicId ?? "");
  const seriesShelf = useSeriesShelf(comicId);
  const [shelfOpen, setShelfOpen] = useState(false);
  const missingIssue =
    isNotFoundError(error) ||
    (error instanceof Error &&
      error.message === "Issue not found for this series");

  if (isLoading) {
    return (
      <div className="space-y-5 px-8 pt-5 page-transition">
        <h1 className="sr-only">
          <Trans>Issue</Trans>
        </h1>
        <Skeleton className="h-4 w-64" />
        <div className="flex gap-5">
          <Skeleton className="aspect-[2/3] w-24 rounded-md" />
          <div className="flex-1 space-y-3 pt-1">
            <Skeleton className="h-8 w-1/2" />
            <Skeleton className="h-4 w-1/3" />
          </div>
        </div>
      </div>
    );
  }

  if (isError && !missingIssue) {
    return (
      <div className="px-8 pt-5 page-transition">
        <ErrorDisplay
          error={error}
          title={t`Unable to load issue`}
          onRetry={() => {
            void refetch();
          }}
          isRetrying={isFetching}
        />
      </div>
    );
  }

  if (isError || !data) {
    const message = error instanceof Error ? error.message : t`Issue not found`;
    return (
      <div className="px-8 page-transition">
        <div className="mx-auto max-w-lg py-16 text-center">
          <h1 className="text-lg font-semibold">
            <Trans>Issue not found</Trans>
          </h1>
          <p className="mt-2 text-sm text-foreground-2">{message}</p>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
            {comicId ? (
              <Link
                to={`/library/${comicId}`}
                className={buttonVariants({ size: "toolbar" })}
              >
                <Trans>Back to series</Trans>
              </Link>
            ) : null}
            <Link
              to="/library"
              className={buttonVariants({
                variant: "outline",
                size: "toolbar",
              })}
            >
              <Trans>Back to library</Trans>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const { issue, series } = data;
  const seriesName = series?.ComicName ?? issue.ComicName ?? t`Series`;
  const number = issueNumber(issue);
  const name = issueName(issue);
  const title = number ? `${seriesName} #${number}` : name || seriesName;
  const status = issueStatus(issue);
  const releaseDate =
    issue.ReleaseDate ??
    issue.releaseDate ??
    issue.IssueDate ??
    issue.issueDate;
  const location = issue.Location ?? issue.location;
  const seriesMeta = [series?.ComicPublisher, series?.ComicYear]
    .filter(Boolean)
    .join(" · ");

  const rawStatus = String(issue.Status ?? issue.status ?? "");
  const size = sizeLabel(issue.ComicSize);
  // Rows with nothing to say are left out, so the column never reads as a
  // list of dashes (#1507).
  const details: { label: string; value: ReactNode; mono?: boolean }[] = [
    ...(releaseDate
      ? [{ label: t`Released`, value: field(releaseDate), mono: true }]
      : []),
    ...(issue.DigitalDate && issue.DigitalDate !== releaseDate
      ? [
          {
            label: t`Digital date`,
            value: field(issue.DigitalDate),
            mono: true,
          },
        ]
      : []),
    ...(location
      ? [{ label: t`File on disk`, value: String(location), mono: true }]
      : []),
    ...(size ? [{ label: t`Size`, value: size, mono: true }] : []),
    ...(issue.Arc ? [{ label: t`Story arc`, value: field(issue.Arc) }] : []),
  ];

  return (
    <div className="flex h-full min-h-0 flex-col page-transition">
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
        <div className="px-4 pt-5 pb-5 md:px-8">
          <nav
            aria-label={t`Breadcrumb`}
            className="mb-4 flex items-center gap-2 text-[13px] text-foreground-2"
          >
            <Link to="/library" className="hover:text-foreground">
              <Trans>Library</Trans>
            </Link>
            <span className="text-muted-foreground">/</span>
            <Link
              to={`/library/${comicId}`}
              className="truncate hover:text-foreground"
            >
              {seriesName}
            </Link>
            <span className="text-muted-foreground">/</span>
            <span className="shrink-0 text-foreground">
              {number ? `#${number}` : title}
            </span>
            <span
              className="mono-meta ms-auto hidden shrink-0 sm:inline"
              data-testid="issue-detail-ids"
            >
              <Trans>
                series:{comicId} · issue:{issueId}
              </Trans>
            </span>
          </nav>

          <div className="flex flex-col gap-4 border-b border-border-subtle pb-5 md:flex-row md:items-start">
            <div className="min-w-0 flex-1">
              <h1
                className="text-[26px] font-semibold leading-tight tracking-[-0.02em]"
                data-testid="issue-detail-title"
              >
                {title}
              </h1>
              {name && (
                <div className="mt-0.5 text-sm text-foreground-2">{name}</div>
              )}
              {cause ? (
                <p
                  className="mt-1.5 flex items-center gap-2 text-[13px] text-foreground"
                  data-testid="issue-cause-line"
                >
                  <span
                    aria-hidden="true"
                    className="size-1.5 shrink-0 rounded-full"
                    style={{ background: "var(--status-paused)" }}
                  />
                  {cause.headline}.
                </p>
              ) : null}
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-foreground-2">
                <IssueStatusMenu
                  current={status}
                  label={t`Change status for ${title}`}
                  disabled={!issueId || setIssueStatus.isPending}
                  onSelect={(next) => {
                    if (!issueId) return;
                    setIssueStatus.mutate(
                      { issueId, status: next },
                      {
                        onError: (statusError) =>
                          addToast({
                            type: "error",
                            title: t`Error`,
                            description: t`Failed to update status: ${ph({ message: statusError.message })}`,
                          }),
                      },
                    );
                  }}
                />
                <Link
                  to={`/library/${comicId}`}
                  className="hover:text-foreground hover:underline"
                >
                  {seriesName}
                </Link>
                {seriesMeta && <span>{seriesMeta}</span>}
              </div>
            </div>

            {issueId ? (
              <div className="flex shrink-0 flex-wrap items-center gap-2">
                {cause && <IssueCauseActions cause={cause} label={title} />}
                {!cause && searchable(rawStatus) ? (
                  <Button
                    type="button"
                    size="toolbar"
                    disabled={searchIssue.isPending}
                    onClick={() =>
                      searchIssue.mutate(issueId, {
                        onSuccess: (result) =>
                          addToast({
                            type: result.success ? "info" : "error",
                            message:
                              result.message ||
                              result.error ||
                              (result.success
                                ? t`Search accepted.`
                                : t`Unable to start this search.`),
                          }),
                        onError: (err) =>
                          addToast({
                            type: "error",
                            message: getErrorMessage(err),
                          }),
                      })
                    }
                  >
                    <Search />
                    <Trans>Search now</Trans>
                  </Button>
                ) : null}
                {!cause && wantable(rawStatus) ? (
                  <Button
                    type="button"
                    size="toolbar"
                    disabled={setIssueStatus.isPending}
                    onClick={() =>
                      setIssueStatus.mutate(
                        { issueId, status: "Wanted" },
                        {
                          onError: (statusError) =>
                            addToast({
                              type: "error",
                              description: t`Failed to update status: ${ph({ message: statusError.message })}`,
                            }),
                        },
                      )
                    }
                  >
                    <Star />
                    <Trans>Mark wanted</Trans>
                  </Button>
                ) : null}
                {shelfEnabled && comicId ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="toolbar"
                    className="bg-surface-2"
                    onClick={() => setShelfOpen(true)}
                  >
                    <LibraryBig />
                    <Trans>Print copies</Trans>
                    <span className="mono-meta">
                      {seriesShelf.data?.issues[issueId] ?? 0}
                    </span>
                  </Button>
                ) : null}
                <Link
                  to={`/activity?scope_type=issue&scope_id=${encodeURIComponent(issueId)}`}
                  className={buttonVariants({
                    variant: "outline",
                    size: "toolbar",
                    className: "bg-surface-2",
                  })}
                  aria-label={t`View activity for this issue`}
                >
                  <Activity />
                  <Trans>Activity</Trans>
                </Link>
              </div>
            ) : null}
          </div>
        </div>

        <div className="grid gap-8 px-4 pb-8 md:px-8 lg:grid-cols-[minmax(0,1fr)_380px]">
          {issueId ? (
            <IssueStory
              issueId={issueId}
              cause={cause}
              search={story.data?.search}
            />
          ) : (
            <div />
          )}

          <aside
            aria-label={t`Details`}
            className="min-w-0 lg:border-s lg:border-border-subtle lg:ps-8"
          >
            <SectionHeader title={t`Details`} />
            {details.length === 0 && !story.data && (
              <p className="py-1.5 text-[13px] text-foreground-2">
                <Trans>No file or release details yet.</Trans>
              </p>
            )}
            <dl>
              {details.map((row) => (
                <div
                  key={row.label}
                  className="flex items-baseline justify-between gap-4 py-1.5 text-[13px]"
                >
                  <dt className="text-foreground-2">{row.label}</dt>
                  <dd
                    className={
                      row.mono
                        ? "min-w-0 break-all text-end font-mono text-xs leading-5"
                        : "text-end"
                    }
                  >
                    {row.value}
                  </dd>
                </div>
              ))}
              {story.data && (
                <div className="flex items-baseline justify-between gap-4 py-1.5 text-[13px]">
                  <dt className="text-foreground-2">
                    <Trans>Attempts</Trans>
                  </dt>
                  <dd
                    className="text-end font-mono text-xs leading-5"
                    data-testid="issue-attempts"
                  >
                    {attemptsLine(story.data.attempts)}
                  </dd>
                </div>
              )}
            </dl>
            {story.data && <Candidates details={story.data} />}
            <div className="mt-6">
              <SectionHeader title={t`Log`} />
              {story.data?.log.lines.length ? (
                <pre
                  data-testid="issue-log-lines"
                  className="overflow-x-auto rounded-md border border-border-subtle bg-surface-1 px-3 py-2 font-mono text-[11px] leading-5 whitespace-pre-wrap break-all text-foreground-2"
                >
                  {story.data.log.lines.map(shortLogLine).join("\n")}
                </pre>
              ) : (
                <p className="text-[13px] text-foreground-2">
                  <Trans>
                    Every line Comicarr wrote about this issue is in the full
                    log.
                  </Trans>
                </p>
              )}
              <Link
                to={
                  story.data?.log.query
                    ? `/settings?section=logs&logq=${encodeURIComponent(story.data.log.query)}`
                    : "/settings?section=logs"
                }
                className="mt-2 inline-block text-[13px] text-foreground underline-offset-2 hover:underline"
              >
                <Trans>Open full log</Trans>
              </Link>
            </div>
          </aside>
        </div>
      </div>
      <ShelfSheet
        target={
          shelfOpen && comicId && issueId
            ? { item: { ComicID: comicId, ItemID: issueId }, title }
            : null
        }
        onClose={() => setShelfOpen(false)}
      />
    </div>
  );
}
