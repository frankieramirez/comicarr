import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { Activity } from "lucide-react";
import IssueStatusMenu from "@/components/series/IssueStatusMenu";
import { SectionHeader } from "@/components/dashboard/DashboardPanel";
import { buttonVariants } from "@/components/ui/button";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { useIssueDetail } from "@/hooks/useIssueDetail";
import { useSetIssueStatus } from "@/hooks/useSeries";
import type { IssueMetadata } from "@/hooks/useIssueDetail";
import { isNotFoundError } from "@/lib/api";

function issueNumber(issue: IssueMetadata): string {
  return String(issue.Issue_Number ?? issue.number ?? "").trim();
}

function issueTitle(issue: IssueMetadata): string {
  const name = issue.IssueName ?? issue.name;
  if (name && String(name).trim()) return String(name);
  const number = issueNumber(issue);
  return number ? `Issue ${number}` : "Issue";
}

function issueStatus(issue: IssueMetadata): string {
  return issue.displayState ?? issue.status ?? issue.Status ?? "Unknown";
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
  const { addToast } = useToast();
  const missingIssue =
    isNotFoundError(error) ||
    (error instanceof Error &&
      error.message === "Issue not found for this series");

  if (isLoading) {
    return (
      <div className="space-y-5 px-8 pt-5 page-transition">
        <h1 className="sr-only">Issue</h1>
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
          title="Unable to load issue"
          onRetry={() => {
            void refetch();
          }}
          isRetrying={isFetching}
        />
      </div>
    );
  }

  if (isError || !data) {
    const message = error instanceof Error ? error.message : "Issue not found";
    return (
      <div className="px-8 page-transition">
        <div className="mx-auto max-w-lg py-16 text-center">
          <h1 className="text-lg font-semibold">Issue not found</h1>
          <p className="mt-2 text-sm text-foreground-2">{message}</p>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
            {comicId ? (
              <Link
                to={`/library/${comicId}`}
                className={buttonVariants({ size: "toolbar" })}
              >
                Back to series
              </Link>
            ) : null}
            <Link
              to="/library"
              className={buttonVariants({
                variant: "outline",
                size: "toolbar",
              })}
            >
              Back to library
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const { issue, series } = data;
  const seriesName = series?.ComicName ?? issue.ComicName ?? "Series";
  const number = issueNumber(issue);
  const title = issueTitle(issue);
  const status = issueStatus(issue);
  const releaseDate =
    issue.ReleaseDate ??
    issue.releaseDate ??
    issue.IssueDate ??
    issue.issueDate;
  const location = issue.Location ?? issue.location;
  const imageUrl = issue.ImageURL ?? issue.imageURL ?? issue.ArtworkURL;
  const seriesMeta = [series?.ComicPublisher, series?.ComicYear]
    .filter(Boolean)
    .join(" · ");
  const hasName = Boolean(String(issue.IssueName ?? issue.name ?? "").trim());

  const details: { label: string; value: ReactNode; mono?: boolean }[] = [
    { label: "Release date", value: field(releaseDate), mono: true },
    ...(issue.DigitalDate && issue.DigitalDate !== releaseDate
      ? [{ label: "Digital date", value: field(issue.DigitalDate), mono: true }]
      : []),
    ...(issue.ComicSize
      ? [{ label: "Size", value: field(issue.ComicSize), mono: true }]
      : []),
    ...(issue.Arc ? [{ label: "Story arc", value: field(issue.Arc) }] : []),
  ];

  return (
    <div className="flex h-full min-h-0 flex-col page-transition">
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
        <div className="relative shrink-0 overflow-hidden">
          {/* Blurred cover wash, the same faint treatment as the series page. */}
          {imageUrl && (
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 top-0 h-[260px] opacity-[0.16] dark:opacity-25"
              style={{
                backgroundImage: `url(${imageUrl})`,
                backgroundSize: "cover",
                backgroundPosition: "center 30%",
                filter: "blur(48px) saturate(1.2)",
                maskImage: "linear-gradient(to bottom, black, transparent)",
              }}
            />
          )}

          <div className="relative px-8 pt-5 pb-6">
            <nav
              aria-label="Breadcrumb"
              className="mb-5 flex items-center gap-2 text-[13px] text-foreground-2"
            >
              <Link to="/library" className="hover:text-foreground">
                Library
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
                className="mono-meta ml-auto hidden shrink-0 sm:inline"
                data-testid="issue-detail-ids"
              >
                series:{comicId} · issue:{issueId}
              </span>
            </nav>

            <div className="flex flex-col gap-5 md:flex-row md:items-start">
              <div className="aspect-[2/3] w-24 shrink-0 overflow-hidden rounded-md bg-surface-2 shadow-sm">
                {imageUrl ? (
                  <img
                    src={imageUrl}
                    alt={title}
                    className="h-full w-full object-cover"
                    onError={(event) => {
                      event.currentTarget.style.display = "none";
                    }}
                  />
                ) : null}
              </div>

              <div className="min-w-0 flex-1 pt-1">
                {number && hasName ? (
                  <div className="mono-label mb-1">Issue {number}</div>
                ) : null}
                <h1
                  className="text-[28px] font-semibold leading-tight tracking-[-0.02em]"
                  data-testid="issue-detail-title"
                >
                  {title}
                </h1>

                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-foreground-2">
                  <IssueStatusMenu
                    current={status}
                    label={`Change status for ${title}`}
                    disabled={!issueId || setIssueStatus.isPending}
                    onSelect={(next) => {
                      if (!issueId) return;
                      setIssueStatus.mutate(
                        { issueId, status: next },
                        {
                          onError: (statusError) =>
                            addToast({
                              type: "error",
                              title: "Error",
                              description: `Failed to update status: ${statusError.message}`,
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
                <div className="flex shrink-0 flex-wrap items-center gap-2 md:pt-8">
                  <Link
                    to={`/activity?scope_type=issue&scope_id=${encodeURIComponent(issueId)}`}
                    className={buttonVariants({
                      variant: "outline",
                      size: "toolbar",
                      className: "bg-surface-2",
                    })}
                    aria-label="View activity for this issue"
                  >
                    <Activity />
                    Activity
                  </Link>
                </div>
              ) : null}
            </div>
          </div>
        </div>

        <section aria-label="Details" className="px-8 pb-8">
          <SectionHeader title="Details" />
          <dl className="max-w-3xl border-t border-border-subtle">
            {details.map((row) => (
              <div
                key={row.label}
                className="grid grid-cols-[140px_minmax(0,1fr)] gap-4 border-b border-border-subtle px-2 py-2 text-[13px]"
              >
                <dt className="text-foreground-2">{row.label}</dt>
                <dd className={row.mono ? "font-mono text-xs leading-5" : ""}>
                  {row.value}
                </dd>
              </div>
            ))}
            <div className="grid grid-cols-[140px_minmax(0,1fr)] gap-4 border-b border-border-subtle px-2 py-2 text-[13px]">
              <dt className="text-foreground-2">File</dt>
              <dd
                className={
                  location
                    ? "break-all font-mono text-xs leading-5"
                    : "text-muted-foreground"
                }
              >
                {location ? location : "Not in your library yet"}
              </dd>
            </div>
          </dl>
        </section>
      </div>
    </div>
  );
}
