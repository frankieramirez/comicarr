import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import {
  Pause,
  Play,
  RefreshCw,
  Trash2,
  Search,
  MoreHorizontal,
} from "lucide-react";
import {
  useSeriesDetail,
  usePauseSeries,
  useResumeSeries,
  useRefreshSeries,
  useDeleteSeries,
} from "@/hooks/useSeries";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import type { ComicOrManga, Issue } from "@/types";

type IssueFilter = "all" | "have" | "missing" | "monitored";

export default function SeriesDetailPage() {
  const { comicId } = useParams<{ comicId: string }>();
  const navigate = useNavigate();
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [filter, setFilter] = useState<IssueFilter>("all");
  const { addToast } = useToast();

  const { data: seriesData, isLoading, error } = useSeriesDetail(comicId);
  const pauseMutation = usePauseSeries();
  const resumeMutation = useResumeSeries();
  const refreshMutation = useRefreshSeries();
  const deleteMutation = useDeleteSeries();

  if (isLoading) {
    return (
      <div className="p-5 space-y-4">
        <Skeleton className="h-6 w-64" />
        <div
          className="grid gap-7"
          style={{ gridTemplateColumns: "140px 1fr 260px" }}
        >
          <Skeleton className="aspect-[2/3] w-[140px]" />
          <div className="space-y-3">
            <Skeleton className="h-8 w-2/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-4/5" />
          </div>
          <Skeleton className="h-40 w-full" />
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
          <div className="font-semibold mb-1">Failed to load series</div>
          <div className="text-[12px]">
            {error?.message || "Series not found."}
          </div>
          <Link
            to="/library"
            className="inline-block mt-3 font-mono text-[11px] underline"
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
  const issues: Issue[] = seriesData.issues || [];
  const isPaused = comic.Status?.toLowerCase() === "paused";

  const isManga =
    comic.ContentType === "manga" ||
    comicId?.startsWith("md-") ||
    comicId?.startsWith("mal-");

  const have = comic.Have || 0;
  const total = comic.Total || 0;
  const missing = Math.max(0, total - have);
  const completionPct = total > 0 ? Math.round((have / total) * 100) : 0;
  const slug = (comic.ComicName || "").toLowerCase().replace(/\s+/g, "-");

  const haveCount = issues.filter((i) => i.Status === "Downloaded").length;
  const missingCount = issues.filter((i) => i.Status !== "Downloaded").length;

  const filteredIssues =
    filter === "have"
      ? issues.filter((i) => i.Status === "Downloaded")
      : filter === "missing"
        ? issues.filter((i) => i.Status !== "Downloaded")
        : issues;

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
    "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[5px] border text-[12px] hover:bg-secondary/50 transition-colors";

  return (
    <div className="h-full flex flex-col page-transition">
      {/* Breadcrumb bar */}
      <div
        className="px-5 py-3.5 border-b flex items-center gap-2.5 font-mono text-[11px]"
        style={{
          borderColor: "var(--border)",
          color: "var(--muted-foreground)",
        }}
      >
        <Link to="/library" className="hover:text-foreground transition-colors">
          library
        </Link>
        <span style={{ color: "var(--text-muted)" }}>/</span>
        <span>{isManga ? "manga" : "comics"}</span>
        <span style={{ color: "var(--text-muted)" }}>/</span>
        <span style={{ color: "var(--foreground)" }}>{slug}</span>
        <span className="ml-auto">
          cv:{comic.ComicID} ·{" "}
          {comic.LatestDate ? `last sync ${comic.LatestDate}` : "unsynced"}
        </span>
      </div>

      {/* Hero */}
      <div
        className="px-5 py-6 border-b grid gap-7"
        style={{
          borderColor: "var(--border)",
          gridTemplateColumns: "140px 1fr 260px",
        }}
      >
        {/* Cover */}
        <div
          className="aspect-[2/3] rounded-[5px] overflow-hidden border"
          style={{ borderColor: "var(--border)" }}
        >
          {comic.ComicImage && (
            <img
              src={comic.ComicImage}
              alt={comic.ComicName}
              className="w-full h-full object-cover"
              onError={(e: React.SyntheticEvent<HTMLImageElement>) => {
                e.currentTarget.style.display = "none";
              }}
            />
          )}
        </div>

        {/* Info */}
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-2 font-mono text-[10px] tracking-[0.08em] uppercase">
            <span
              className="px-1.5 py-0.5 rounded-[3px]"
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

          <h1 className="text-[28px] font-bold tracking-[-0.02em] leading-tight mb-2">
            {comic.ComicName}
          </h1>

          {comic.Description && (
            <p
              className="text-[13px] leading-relaxed mb-3.5 max-w-[640px]"
              style={{ color: "var(--muted-foreground)" }}
            >
              {comic.Description}
            </p>
          )}

          <div className="flex items-center gap-2">
            <button
              type="button"
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-[5px] text-[12px] font-semibold"
              style={{
                background: "var(--primary)",
                color: "var(--primary-foreground)",
              }}
            >
              <Search className="w-3.5 h-3.5" />
              Search all missing
            </button>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={refreshMutation.isPending}
              className={ghostBtn}
              style={{ borderColor: "var(--border)" }}
            >
              <RefreshCw
                className={`w-3.5 h-3.5 ${refreshMutation.isPending ? "animate-spin" : ""}`}
              />
              Refresh
            </button>
            <button
              type="button"
              onClick={handlePauseResume}
              disabled={pauseMutation.isPending || resumeMutation.isPending}
              className={ghostBtn}
              style={{ borderColor: "var(--border)" }}
            >
              {isPaused ? (
                <Play className="w-3.5 h-3.5" />
              ) : (
                <Pause className="w-3.5 h-3.5" />
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
                <MoreHorizontal className="w-3.5 h-3.5" />
              </button>
            ) : (
              <>
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={deleteMutation.isPending}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[5px] text-[12px] font-semibold"
                  style={{ background: "var(--status-error)", color: "white" }}
                >
                  <Trash2 className="w-3.5 h-3.5" />
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

        {/* Status card */}
        <div
          className="rounded-[6px] border"
          style={{ borderColor: "var(--border)", background: "var(--card)" }}
        >
          <div
            className="px-3 py-2.5 border-b font-mono text-[10px] tracking-[0.1em] uppercase"
            style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
          >
            Status
          </div>
          <div className="px-3 py-2.5">
            <div className="flex items-baseline gap-2 mb-1.5">
              <div className="text-[28px] font-bold tracking-[-0.02em] leading-none">
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
              className="h-1 rounded-full overflow-hidden mb-2.5"
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
                  ["status", isPaused ? "paused" : "active"],
                ] as const
              ).map(([label, value], i) => (
                <div
                  key={label}
                  className="flex justify-between py-1"
                  style={{
                    borderTop: i > 1 ? "1px solid var(--border)" : "none",
                  }}
                >
                  <span style={{ color: "var(--text-muted)" }}>{label}</span>
                  <span>{value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Issues header */}
      <div
        className="px-5 py-2.5 border-b flex items-center gap-3"
        style={{ borderColor: "var(--border)" }}
      >
        <div className="text-[13px] font-semibold">
          {isManga ? "Chapters" : "Issues"}
        </div>
        <div
          className="font-mono text-[10px] tracking-[0.08em] uppercase"
          style={{ color: "var(--text-muted)" }}
        >
          {total} · grouped by arc
        </div>
        <div className="ml-auto flex gap-1.5 font-mono text-[10px]">
          {(
            [
              ["all", `All ${total}`],
              ["have", `Have ${haveCount}`],
              ["missing", `Missing ${missingCount}`],
              ["monitored", `Monitored ${total}`],
            ] as const
          ).map(([key, label]) => {
            const active = filter === key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => setFilter(key as IssueFilter)}
                className="px-2 py-0.5 rounded-full border transition-colors"
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

      {/* Issues table */}
      <div className="flex-1 overflow-auto">
        <div
          className="px-5 py-2 grid gap-3 font-mono text-[10px] tracking-[0.1em] uppercase border-b"
          style={{
            gridTemplateColumns: "40px 40px 1fr 140px 110px 110px",
            borderColor: "var(--border)",
            color: "var(--text-muted)",
            background: "var(--card)",
          }}
        >
          <div />
          <div>#</div>
          <div>title</div>
          <div>arc</div>
          <div>date</div>
          <div>status</div>
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
            const haveIt = issue.Status === "Downloaded";
            const wanted = issue.Status === "Wanted";
            const arc = (issue as unknown as { Arc?: string }).Arc || "—";
            return (
              <div
                key={issue.IssueID}
                className="px-5 py-2 grid gap-3 items-center border-b text-[12px]"
                style={{
                  gridTemplateColumns: "40px 40px 1fr 140px 110px 110px",
                  borderColor: "var(--border)",
                }}
              >
                <div
                  className="w-3 h-3 rounded-sm border"
                  style={{ borderColor: "var(--border)" }}
                />
                <div
                  className="font-mono"
                  style={{ color: "var(--muted-foreground)" }}
                >
                  #{String(issue.Issue_Number).padStart(2, "0")}
                </div>
                <div className="truncate">
                  <Link
                    to={`/library/${comicId}/issue/${issue.IssueID}`}
                    className="hover:text-primary transition-colors"
                  >
                    {issue.IssueName || `Issue ${issue.Issue_Number}`}
                  </Link>
                </div>
                <div
                  className="text-[11px] truncate"
                  style={{ color: "var(--muted-foreground)" }}
                >
                  {arc}
                </div>
                <div
                  className="font-mono text-[10px]"
                  style={{ color: "var(--muted-foreground)" }}
                >
                  {issue.IssueDate || "—"}
                </div>
                <div
                  className="inline-flex items-center gap-1.5 font-mono text-[10px]"
                  style={{
                    color: haveIt
                      ? "var(--status-active)"
                      : wanted
                        ? "var(--primary)"
                        : "var(--text-muted)",
                  }}
                >
                  <span
                    className="w-[5px] h-[5px] rounded-full"
                    style={{
                      background: haveIt
                        ? "var(--status-active)"
                        : wanted
                          ? "var(--primary)"
                          : "var(--text-muted)",
                    }}
                  />
                  {haveIt ? "have" : wanted ? "wanted" : "skipped"}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
