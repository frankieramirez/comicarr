import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { BookMarked, RefreshCw, Trash2, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import {
  useDelStoryArc,
  useWantAllArcIssues,
  useRefreshStoryArc,
} from "@/hooks/useStoryArcs";
import type { StoryArc } from "@/types";

interface ArcHeaderProps {
  arc: StoryArc;
}

export default function ArcHeader({ arc }: ArcHeaderProps) {
  const navigate = useNavigate();
  const { addToast } = useToast();
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const deleteMutation = useDelStoryArc();
  const wantAllMutation = useWantAllArcIssues();
  const refreshMutation = useRefreshStoryArc();

  const anyPending =
    deleteMutation.isPending ||
    wantAllMutation.isPending ||
    refreshMutation.isPending;

  const bannerUrl = arc.ArcImage ? `/cache/storyarcs/${arc.ArcImage}` : null;

  const handleWantAll = () => {
    wantAllMutation.mutate(arc.StoryArcID, {
      onSuccess: (data) => {
        const queued = data?.data?.queued ?? 0;
        addToast({
          type: "success",
          title: "Issues Queued",
          description: `${queued} issue${queued !== 1 ? "s" : ""} marked as Wanted.`,
        });
      },
      onError: () => {
        addToast({
          type: "error",
          title: "Error",
          description: "Failed to queue issues.",
        });
      },
    });
  };

  const handleRefresh = () => {
    refreshMutation.mutate(arc.StoryArcID, {
      onSuccess: () => {
        addToast({
          type: "success",
          title: "Refreshing",
          description: `Refreshing ${arc.StoryArc} from ComicVine...`,
        });
      },
      onError: () => {
        addToast({
          type: "error",
          title: "Error",
          description: "Failed to refresh story arc.",
        });
      },
    });
  };

  const handleDelete = () => {
    deleteMutation.mutate(arc.StoryArcID, {
      onSuccess: () => {
        setShowDeleteConfirm(false);
        addToast({
          type: "success",
          title: "Arc Deleted",
          description: `${arc.StoryArc} has been removed.`,
        });
        navigate("/story-arcs");
      },
      onError: () => {
        setShowDeleteConfirm(false);
        addToast({
          type: "error",
          title: "Error",
          description: "Failed to delete story arc.",
        });
      },
    });
  };

  const missing = Math.max(0, arc.Total - arc.Have);
  const sub = [arc.Publisher, arc.SpanYears].filter(Boolean).join(" · ");
  const heldPct =
    arc.Total > 0 ? Math.min(100, (arc.Have / arc.Total) * 100) : 0;

  return (
    <div className="relative shrink-0 overflow-hidden">
      {bannerUrl && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-0 h-[260px] opacity-[0.16] dark:opacity-25"
          style={{
            backgroundImage: `url(${bannerUrl})`,
            backgroundSize: "cover",
            backgroundPosition: "center 30%",
            filter: "blur(48px) saturate(1.2)",
            maskImage: "linear-gradient(to bottom, black, transparent)",
          }}
        />
      )}

      <div className="relative px-8 pt-5">
        <nav
          aria-label="Breadcrumb"
          className="mb-5 flex items-center gap-2 text-[13px] text-foreground-2"
        >
          <Link to="/story-arcs" className="hover:text-foreground">
            Story arcs
          </Link>
          <span className="text-muted-foreground">/</span>
          <span className="truncate text-foreground">{arc.StoryArc}</span>
          {arc.CV_ArcID && (
            <span className="mono-meta ml-auto hidden shrink-0 sm:inline">
              cv:{arc.CV_ArcID}
            </span>
          )}
        </nav>

        <div className="flex flex-col gap-5 md:flex-row md:items-start">
          <div className="grid aspect-[2/3] w-24 shrink-0 place-items-center overflow-hidden rounded-md bg-surface-2 shadow-sm">
            {bannerUrl ? (
              <img
                src={bannerUrl}
                alt={arc.StoryArc}
                className="h-full w-full object-cover"
                onError={(event) => {
                  event.currentTarget.style.display = "none";
                }}
              />
            ) : (
              <BookMarked
                className="size-6 text-muted-foreground"
                aria-hidden="true"
              />
            )}
          </div>

          <div className="min-w-0 flex-1 pt-1">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.02em]">
                {arc.StoryArc}
              </h1>
              <span className="rounded-md border border-border-strong px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.04em] text-muted-foreground">
                Arc
              </span>
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-foreground-2">
              {sub && <span>{sub}</span>}
              <span className="font-mono text-xs text-foreground">
                {arc.Have} / {arc.Total}
              </span>
              <span>
                {missing > 0
                  ? `${missing} missing`
                  : arc.Total > 0
                    ? "Complete"
                    : "No issues yet"}
              </span>
            </div>
          </div>

          <div className="flex shrink-0 flex-wrap items-center gap-2 md:pt-8">
            {showDeleteConfirm ? (
              <>
                <span className="text-[13px] text-foreground-2">
                  Delete this arc?
                </span>
                <Button
                  type="button"
                  variant="destructive"
                  size="toolbar"
                  onClick={handleDelete}
                  disabled={anyPending}
                  className="font-semibold"
                >
                  <Trash2 />
                  Confirm delete
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="toolbar"
                  onClick={() => setShowDeleteConfirm(false)}
                >
                  Cancel
                </Button>
              </>
            ) : (
              <>
                <Button
                  type="button"
                  size="toolbar"
                  onClick={handleWantAll}
                  disabled={anyPending || missing === 0}
                >
                  <Search />
                  Want all
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="toolbar"
                  className="bg-surface-2"
                  onClick={handleRefresh}
                  disabled={anyPending}
                >
                  <RefreshCw
                    className={refreshMutation.isPending ? "animate-spin" : ""}
                  />
                  Refresh
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => setShowDeleteConfirm(true)}
                  disabled={anyPending}
                  aria-label="Delete story arc"
                >
                  <Trash2 />
                </Button>
              </>
            )}
          </div>
        </div>

        {/* Held versus the rest of the arc: one thin bar, no percentage. */}
        <div
          className="mt-5 flex h-1 gap-0.5 overflow-hidden rounded-full bg-surface-3"
          role="img"
          aria-label={`${Math.round(heldPct)}% held: ${arc.Have} of ${arc.Total}`}
        >
          <div
            className="rounded-full"
            style={{
              width: `${heldPct}%`,
              background: "var(--status-downloaded)",
            }}
          />
        </div>
      </div>
    </div>
  );
}
