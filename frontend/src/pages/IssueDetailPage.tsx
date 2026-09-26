import { Link, useParams } from "react-router-dom";
import { Activity, ChevronRight, Library } from "lucide-react";
import IssueStatusMenu from "@/components/series/IssueStatusMenu";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { useIssueDetail } from "@/hooks/useIssueDetail";
import { useSetIssueStatus } from "@/hooks/useSeries";
import type { IssueMetadata } from "@/hooks/useIssueDetail";

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
  const { data, isLoading, error, isError } = useIssueDetail(comicId, issueId);
  const setIssueStatus = useSetIssueStatus();
  const { addToast } = useToast();

  if (isLoading) {
    return (
      <div className="space-y-6 p-5 page-transition">
        <Skeleton className="h-5 w-64" />
        <Skeleton className="h-10 w-1/2" />
        <Skeleton className="h-40 w-full rounded-lg" />
      </div>
    );
  }

  if (isError || !data) {
    const message = error instanceof Error ? error.message : "Issue not found";
    return (
      <div className="p-5 page-transition">
        <div className="mx-auto max-w-lg py-16 text-center">
          <h1 className="text-lg font-semibold">Issue not found</h1>
          <p className="mt-2 text-sm text-muted-foreground">{message}</p>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-3 text-sm">
            {comicId ? (
              <Link
                to={`/library/${comicId}`}
                className="text-primary hover:underline"
              >
                Back to series
              </Link>
            ) : null}
            <Link to="/library" className="text-primary hover:underline">
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

  return (
    <div className="flex h-full flex-col page-transition">
      <nav
        className="flex items-center gap-1.5 border-b px-5 py-3.5 font-mono text-[11px]"
        style={{
          borderColor: "var(--border)",
          color: "var(--muted-foreground)",
        }}
        aria-label="Breadcrumb"
      >
        <Link
          to="/library"
          className="inline-flex items-center gap-1 transition-colors hover:text-foreground"
        >
          <Library className="h-3.5 w-3.5" />
          library
        </Link>
        <ChevronRight
          className="h-3.5 w-3.5"
          style={{ color: "var(--text-muted)" }}
        />
        <Link
          to={`/library/${comicId}`}
          className="truncate transition-colors hover:text-foreground"
        >
          {seriesName}
        </Link>
        <ChevronRight
          className="h-3.5 w-3.5"
          style={{ color: "var(--text-muted)" }}
        />
        <span className="truncate" style={{ color: "var(--foreground)" }}>
          {number ? `#${number}` : title}
        </span>
      </nav>

      {/* The breadcrumb stays; the issue body scrolls under it. */}
      <div className="flex-1 min-h-0 overflow-auto">
        <div className="grid gap-7 border-b px-5 py-6 md:grid-cols-[140px_minmax(0,1fr)]">
          <div
            className="aspect-[2/3] w-[112px] overflow-hidden rounded-[5px] border md:w-[140px]"
            style={{
              borderColor: "var(--border)",
              background:
                "color-mix(in oklab, var(--muted-foreground) 8%, transparent)",
            }}
          >
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

          <div className="min-w-0 space-y-3">
            <div className="flex flex-wrap items-center gap-2 font-mono text-[10px] uppercase tracking-[0.08em]">
              {number ? (
                <span style={{ color: "var(--muted-foreground)" }}>
                  Issue {number}
                </span>
              ) : null}
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
            </div>

            <h1
              className="text-[28px] font-bold leading-tight tracking-[-0.02em]"
              data-testid="issue-detail-title"
            >
              {title}
            </h1>

            <p
              className="font-mono text-[11px]"
              style={{ color: "var(--muted-foreground)" }}
              data-testid="issue-detail-ids"
            >
              series:{comicId} · issue:{issueId}
            </p>

            {issueId ? (
              <div className="pt-1">
                <Link
                  to={`/activity?scope_type=issue&scope_id=${encodeURIComponent(issueId)}`}
                  className="inline-flex items-center gap-1.5 rounded-[5px] border px-3 py-1.5 text-[12px] font-semibold transition-colors hover:text-foreground"
                  style={{
                    borderColor: "var(--border)",
                    color: "var(--muted-foreground)",
                  }}
                  aria-label="View activity for this issue"
                >
                  <Activity className="h-3.5 w-3.5" />
                  Activity
                </Link>
              </div>
            ) : null}
          </div>
        </div>

        <div className="px-5 py-6">
          <dl className="grid max-w-2xl gap-4 sm:grid-cols-2">
            <div>
              <dt
                className="font-mono text-[10px] uppercase tracking-[0.08em]"
                style={{ color: "var(--muted-foreground)" }}
              >
                Series
              </dt>
              <dd className="mt-1 text-sm">
                <Link
                  to={`/library/${comicId}`}
                  className="text-primary hover:underline"
                >
                  {seriesName}
                </Link>
              </dd>
            </div>
            <div>
              <dt
                className="font-mono text-[10px] uppercase tracking-[0.08em]"
                style={{ color: "var(--muted-foreground)" }}
              >
                Status
              </dt>
              <dd className="mt-1 text-sm">{field(status)}</dd>
            </div>
            <div>
              <dt
                className="font-mono text-[10px] uppercase tracking-[0.08em]"
                style={{ color: "var(--muted-foreground)" }}
              >
                Release date
              </dt>
              <dd className="mt-1 font-mono text-sm">{field(releaseDate)}</dd>
            </div>
            <div>
              <dt
                className="font-mono text-[10px] uppercase tracking-[0.08em]"
                style={{ color: "var(--muted-foreground)" }}
              >
                Location
              </dt>
              <dd className="mt-1 break-all font-mono text-sm">
                {field(location)}
              </dd>
            </div>
          </dl>
        </div>
      </div>
    </div>
  );
}
