import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  BookMarked,
  RefreshCw,
  Trash2,
  Search,
  Image as ImageIcon,
} from "lucide-react";
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

  return (
    <div className="relative rounded-lg border border-card-border bg-card overflow-hidden">
      {/* Banner */}
      <div className="relative h-40 bg-muted">
        {bannerUrl ? (
          <img
            src={bannerUrl}
            alt={arc.StoryArc}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="flex items-center justify-center h-full">
            <ImageIcon className="w-16 h-16 text-muted-foreground/30" />
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/30 to-transparent" />
      </div>

      {/* Content overlay */}
      <div className="p-4 -mt-16 relative z-10">
        <div className="flex items-end justify-between">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <BookMarked className="w-5 h-5 text-white" />
              <h1 className="text-xl font-bold text-white">{arc.StoryArc}</h1>
            </div>
            <div className="flex items-center gap-3 text-sm text-white/80">
              {arc.Publisher && <span>{arc.Publisher}</span>}
              {arc.SpanYears && <span>{arc.SpanYears}</span>}
            </div>
          </div>
        </div>

        {/* Stats + actions */}
        <div className="flex items-center justify-between mt-4">
          <div className="flex items-center gap-4">
            <div className="text-sm">
              <span className="font-semibold text-foreground">{arc.Have}</span>
              <span className="text-muted-foreground">
                {" "}
                / {arc.Total} issues
              </span>
            </div>
            {/* Progress bar */}
            <div className="w-32 bg-muted rounded-full h-2">
              <div
                className="h-2 rounded-full bg-primary transition-all"
                style={{ width: `${Math.min(arc.percent, 100)}%` }}
              />
            </div>
            <span className="text-sm text-muted-foreground">
              {Math.round(arc.percent)}%
            </span>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleWantAll}
              disabled={anyPending}
            >
              <Search className="w-4 h-4 mr-1" />
              Want All
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleRefresh}
              disabled={anyPending}
            >
              <RefreshCw
                className={`w-4 h-4 mr-1 ${refreshMutation.isPending ? "animate-spin" : ""}`}
              />
              Refresh
            </Button>

            {showDeleteConfirm ? (
              <div className="flex items-center gap-1">
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={handleDelete}
                  disabled={anyPending}
                >
                  Confirm
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowDeleteConfirm(false)}
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowDeleteConfirm(true)}
                disabled={anyPending}
              >
                <Trash2 className="w-4 h-4" />
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
