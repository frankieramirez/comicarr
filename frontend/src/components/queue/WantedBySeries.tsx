import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import RelativeTime from "@/components/ui/RelativeTime";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CoverCell } from "@/components/data-table/cells/CoverCell";
import { useToast } from "@/components/ui/toast";
import {
  useSearchWantedIssue,
  useWanted,
  useWantedSeries,
  type WantedSeriesParams,
} from "@/hooks/useQueue";
import { useUnqueueIssue } from "@/hooks/useSeries";
import { getErrorMessage } from "@/lib/api";
import {
  formatWantedAcquisitionAnnotation,
  wantedSeriesWhy as whyLabel,
} from "@/lib/wantedAnnotation";
import { cn } from "@/lib/utils";
import type { WantedBucket, WantedSeries } from "@/types";

const PAGE_SIZE = 50;

const TABS: { value: WantedSeriesParams["state"]; label: string }[] = [
  { value: "all", label: "All" },
  { value: "not_found", label: "Not found" },
  { value: "searching", label: "Searching" },
  { value: "queued", label: "Queued" },
];

const KINDS: { value: WantedSeriesParams["kind"]; label: string }[] = [
  { value: "all", label: "All" },
  { value: "comic", label: "Comics" },
  { value: "manga", label: "Manga" },
];

const SORTS: { value: WantedSeriesParams["sort"]; label: string }[] = [
  { value: "problems", label: "Problems first" },
  { value: "missing", label: "Most missing" },
  { value: "name", label: "Name" },
];

const BUCKET_COLOR: Record<WantedBucket, string> = {
  not_found: "var(--status-paused)",
  searching: "var(--in-flight)",
  queued: "var(--text-muted)",
};

function WhyCell({ series }: { series: WantedSeries }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[13px]">
      <span
        aria-hidden="true"
        className="size-1.5 shrink-0 rounded-full"
        style={{ background: BUCKET_COLOR[series.why] }}
      />
      <span
        className={
          series.why === "queued" ? "text-foreground-2" : "text-foreground"
        }
      >
        {whyLabel(series)}
      </span>
    </span>
  );
}

/** The issues behind one series row, fetched when the row opens. */
function SeriesIssues({ series }: { series: WantedSeries }) {
  const issues = useWanted(200, 0, "", { comicId: series.comicid });
  const searchOne = useSearchWantedIssue();
  const skip = useUnqueueIssue();
  const { addToast } = useToast();

  if (issues.isPending) {
    return (
      <div className="py-2 pl-12">
        <Skeleton className="h-8" />
      </div>
    );
  }
  if (issues.isError) {
    return (
      <p className="py-2 pl-12 text-[13px] text-foreground-2">
        Couldn&apos;t load these issues.
      </p>
    );
  }

  const rows = issues.data?.issues ?? [];
  return (
    <ul data-testid="wanted-series-issues">
      {rows.map((issue) => (
        <li
          key={issue.IssueID}
          className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-border-subtle bg-surface-1 py-2 pr-2 pl-12 text-[13px] md:grid-cols-[minmax(0,1fr)_120px_160px_auto]"
        >
          <span className="min-w-0 truncate">
            <span className="mr-2 font-mono text-xs text-muted-foreground">
              #{issue.Issue_Number}
            </span>
            {issue.IssueName || `${issue.ComicName} #${issue.Issue_Number}`}
          </span>
          <span className="font-mono text-xs text-foreground-2 max-md:hidden">
            {issue.ReleaseDate || issue.IssueDate || "—"}
          </span>
          <span className="text-foreground-2 max-md:hidden">
            {formatWantedAcquisitionAnnotation(issue.acquisition)}
          </span>
          <span className="flex items-center gap-1">
            <Button
              type="button"
              size="compact"
              variant="ghost"
              aria-label={`Search ${issue.ComicName} #${issue.Issue_Number}`}
              disabled={searchOne.isPending}
              onClick={() =>
                searchOne.mutate(issue.IssueID, {
                  onSuccess: (result) =>
                    addToast({
                      type: result.success ? "info" : "error",
                      message:
                        result.message ||
                        result.error ||
                        (result.success
                          ? "Search accepted."
                          : "Unable to start this search."),
                    }),
                  onError: (err) =>
                    addToast({ type: "error", message: getErrorMessage(err) }),
                })
              }
            >
              <Search />
              Search
            </Button>
            <Button
              type="button"
              size="compact"
              variant="ghost"
              disabled={skip.isPending}
              onClick={() =>
                skip.mutate(issue.IssueID, {
                  onError: (err) =>
                    addToast({ type: "error", message: getErrorMessage(err) }),
                })
              }
            >
              Skip
            </Button>
          </span>
        </li>
      ))}
    </ul>
  );
}

function SeriesRow({ series }: { series: WantedSeries }) {
  const [open, setOpen] = useState(false);
  return (
    <li data-testid="wanted-series-row">
      <div className="grid grid-cols-[20px_32px_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-0.5 border-b border-border-subtle py-2 pr-2 md:py-1.5 md:grid-cols-[20px_24px_minmax(0,1fr)_70px_200px_150px_110px]">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-label={`${open ? "Hide" : "Show"} issues for ${series.comic_name}`}
          className="flex size-5 items-center justify-center rounded-sm text-muted-foreground hover:text-foreground"
        >
          <ChevronRight
            className={cn("size-4 transition-transform", open && "rotate-90")}
          />
        </button>
        <div className="row-span-3 [&>div]:h-11 [&>div]:w-8 [&>div]:rounded-[3px] md:row-span-1 md:[&>div]:h-8 md:[&>div]:w-[22px]">
          <CoverCell
            comicId={series.comicid}
            isManga={series.kind === "manga"}
          />
        </div>
        <div className="flex min-w-0 items-center gap-2">
          <Link
            to={`/library/${series.comicid}`}
            className="truncate text-sm font-medium text-foreground hover:underline underline-offset-2"
          >
            {series.comic_name}
          </Link>
          <span className="shrink-0 rounded-md border border-border-strong px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.04em] text-muted-foreground max-md:hidden">
            {series.kind === "manga" ? "Manga" : "Comic"}
          </span>
        </div>
        <span className="text-right font-mono text-sm text-foreground">
          {series.missing.toLocaleString()}
        </span>
        {/* Phones put which and why on their own lines under the name. */}
        <span className="col-start-3 truncate font-mono text-xs text-foreground-2 md:col-start-auto">
          {series.which}
        </span>
        <span className="col-start-3 md:col-start-auto">
          <WhyCell series={series} />
        </span>
        <span className="max-md:hidden">
          <RelativeTime value={series.last_searched_at} compact />
        </span>
      </div>
      {open && <SeriesIssues series={series} />}
    </li>
  );
}

function FilterSelect<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as T)}>
      <SelectTrigger
        aria-label={label}
        className="h-8 w-auto gap-1.5 text-[13px]"
      >
        <span className="text-muted-foreground">{label}</span>
        <SelectValue>
          {(v: string) => options.find((o) => o.value === v)?.label ?? v}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/**
 * Wanted, one row per series (v2 Wanted design): how many issues are
 * missing, which ones, and why, with tabs that filter by reason. A row opens
 * to its issues. The server folds rows into series; this only lays them out.
 */
export default function WantedBySeries({
  search,
  onTotals,
}: {
  search: string;
  /** Reports issue and series totals for the page header. */
  onTotals?: (totals: { issues: number; series: number }) => void;
}) {
  const [state, setState] = useState<WantedSeriesParams["state"]>("all");
  const [kind, setKind] = useState<WantedSeriesParams["kind"]>("all");
  const [sort, setSort] = useState<WantedSeriesParams["sort"]>("problems");
  const [offset, setOffset] = useState(0);
  const query = useWantedSeries({
    limit: PAGE_SIZE,
    offset,
    q: search,
    state,
    kind,
    sort,
  });

  const data = query.data;
  const counts = data?.counts;
  const pagination = data?.pagination;
  const allIssues = state === "all" ? data?.counts.all : undefined;
  const allSeries = state === "all" ? data?.pagination.total : undefined;
  useEffect(() => {
    if (onTotals && allIssues != null && allSeries != null) {
      onTotals({ issues: allIssues, series: allSeries });
    }
  }, [onTotals, allIssues, allSeries]);

  const choose =
    <T,>(set: (v: T) => void) =>
    (value: T) => {
      set(value);
      setOffset(0);
    };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 px-4 pb-3 md:px-8">
        <div
          role="group"
          aria-label="Why it's missing"
          className="-mx-4 flex gap-2 overflow-x-auto px-4 md:mx-0 md:px-0"
        >
          {TABS.map((tab) => (
            <button
              key={tab.value}
              type="button"
              aria-pressed={state === tab.value}
              onClick={() => choose(setState)(tab.value)}
              className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-control border border-border-subtle px-3 text-[13px] text-foreground-2 hover:text-foreground aria-pressed:border-border-strong aria-pressed:bg-surface-2 aria-pressed:font-medium aria-pressed:text-foreground"
            >
              {tab.label}
              <span className="font-mono text-xs text-muted-foreground">
                {(counts?.[tab.value] ?? 0).toLocaleString()}
              </span>
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2 max-md:hidden">
          <FilterSelect
            label="Kind"
            value={kind}
            options={KINDS}
            onChange={choose(setKind)}
          />
          <FilterSelect
            label="Sort"
            value={sort}
            options={SORTS}
            onChange={choose(setSort)}
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 md:px-8">
        <div className="grid grid-cols-[20px_24px_minmax(0,1fr)_70px_200px_150px_110px] gap-x-3 border-b border-border-subtle pb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground max-md:hidden">
          <span className="col-span-3">Series</span>
          <span className="text-right">Missing</span>
          <span>Which</span>
          <span>Why</span>
          <span>Last searched</span>
        </div>

        {query.isPending && (
          <div className="space-y-2 py-3">
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
          </div>
        )}
        {query.isError && (
          <div className="py-4">
            <ErrorDisplay
              error={query.error}
              title="Unable to load wanted series"
              onRetry={() => void query.refetch()}
            />
          </div>
        )}
        {data && data.series.length === 0 && (
          <p className="py-6 text-sm text-foreground-2">
            {search.trim() || state !== "all" || kind !== "all"
              ? "No wanted series match."
              : "Nothing is wanted."}
          </p>
        )}
        {data && data.series.length > 0 && (
          <ul aria-label="Wanted series">
            {data.series.map((series) => (
              <SeriesRow key={series.comicid} series={series} />
            ))}
          </ul>
        )}
      </div>

      {pagination && pagination.total > PAGE_SIZE && (
        <div className="flex shrink-0 items-center justify-between border-t border-border-subtle px-4 py-2 md:px-8">
          <span className="mono-meta">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, pagination.total)} of{" "}
            {pagination.total} series
          </span>
          <span className="flex gap-2">
            <Button
              type="button"
              size="compact"
              variant="outline"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Previous
            </Button>
            <Button
              type="button"
              size="compact"
              variant="outline"
              disabled={!pagination.has_more}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next
            </Button>
          </span>
        </div>
      )}
    </div>
  );
}
