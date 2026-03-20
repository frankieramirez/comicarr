import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import {
  ChevronRight,
  Pause,
  Play,
  RefreshCw,
  Trash2,
  Home,
  BookOpen,
} from "lucide-react";
import {
  useSeriesDetail,
  usePauseSeries,
  useResumeSeries,
  useRefreshSeries,
  useDeleteSeries,
} from "@/hooks/useSeries";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import StatusBadge from "@/components/StatusBadge";
import IssuesTable from "@/components/series/IssuesTable";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import type { ComicOrManga } from "@/types";

export default function SeriesDetailPage() {
  const { comicId } = useParams<{ comicId: string }>();
  const navigate = useNavigate();
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const { addToast } = useToast();

  const { data: seriesData, isLoading, error } = useSeriesDetail(comicId);
  const pauseMutation = usePauseSeries();
  const resumeMutation = useResumeSeries();
  const refreshMutation = useRefreshSeries();
  const deleteMutation = useDeleteSeries();

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="flex space-x-6">
          <Skeleton className="h-64 w-48" />
          <div className="flex-1 space-y-4">
            <Skeleton className="h-8 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-4 w-1/3" />
          </div>
        </div>
      </div>
    );
  }

  if (error || !seriesData) {
    return (
      <div className="text-center py-12">
        <p className="text-red-600 text-lg">Failed to load series</p>
        <p className="text-muted-foreground text-sm mt-2">
          {error?.message || "Series not found"}
        </p>
        <Link to="/" className="mt-4 inline-block">
          <Button variant="outline">Back to Series</Button>
        </Link>
      </div>
    );
  }

  const comic: ComicOrManga = Array.isArray(seriesData.comic)
    ? seriesData.comic[0]
    : seriesData.comic;
  const issues = seriesData.issues || [];
  const isPaused = comic.Status?.toLowerCase() === "paused";

  // Check if this is a manga (either by ContentType field or ComicID prefix)
  const isManga = comic.ContentType === "manga" || comicId?.startsWith("md-");
  const itemLabel = isManga ? "Chapters" : "Issues";

  const handlePauseResume = async () => {
    if (!comicId) return;
    try {
      if (isPaused) {
        await resumeMutation.mutateAsync(comicId);
      } else {
        await pauseMutation.mutateAsync(comicId);
      }
    } catch (error) {
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
    } catch (error) {
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
      navigate("/");
    } catch (error) {
      addToast({
        type: "error",
        title: "Error",
        description: "Failed to delete series",
      });
    }
  };

  return (
    <div className="space-y-6 page-transition">
      {/* Breadcrumb Navigation */}
      <nav className="flex items-center text-sm">
        <Link
          to="/"
          className="flex items-center text-muted-foreground hover:text-foreground transition-colors"
        >
          <Home className="w-4 h-4 mr-1" />
          Library
        </Link>
        <ChevronRight className="w-4 h-4 mx-2 text-muted-foreground/50" />
        <span className="text-foreground font-medium truncate max-w-md">
          {comic.ComicName}
          {comic.ComicYear && (
            <span className="text-muted-foreground font-normal">
              {" "}
              ({comic.ComicYear})
            </span>
          )}
        </span>
      </nav>

      {/* Series Info */}
      <div className="bg-card rounded-lg card-shadow border border-card-border overflow-hidden">
        <div className="p-6">
          <div className="flex flex-col md:flex-row space-y-4 md:space-y-0 md:space-x-6">
            {/* Cover Image */}
            {comic.ComicImage && (
              <div className="flex-shrink-0">
                <img
                  src={comic.ComicImage}
                  alt={comic.ComicName}
                  className="w-48 h-auto rounded shadow-lg"
                  onError={(e: React.SyntheticEvent<HTMLImageElement>) => {
                    e.currentTarget.src =
                      "https://via.placeholder.com/300x450?text=No+Cover";
                  }}
                />
              </div>
            )}

            {/* Series Details */}
            <div className="flex-1 space-y-4">
              <div>
                <div className="flex items-start justify-between">
                  <div>
                    <h1 className="text-3xl font-bold text-foreground">
                      {comic.ComicName}
                    </h1>
                    {comic.ComicYear && (
                      <p className="text-lg text-muted-foreground mt-1">
                        ({comic.ComicYear})
                      </p>
                    )}
                  </div>
                  <StatusBadge status={comic.Status} />
                </div>

                {comic.ComicPublisher && (
                  <p className="text-muted-foreground mt-2">
                    <span className="font-medium">Publisher:</span>{" "}
                    {comic.ComicPublisher}
                  </p>
                )}
              </div>

              {comic.Description && (
                <div>
                  <h3 className="font-medium text-foreground mb-2">
                    Description
                  </h3>
                  <p className="text-muted-foreground text-sm leading-relaxed">
                    {comic.Description}
                  </p>
                </div>
              )}

              <div className="flex items-center space-x-4 text-sm">
                {isManga && (
                  <Badge variant="default" className="flex items-center gap-1">
                    <BookOpen className="w-3 h-3" />
                    Manga
                  </Badge>
                )}
                <div>
                  <span className="font-medium text-foreground">
                    Total {itemLabel}:
                  </span>{" "}
                  <span className="text-muted-foreground">
                    {comic.Total || 0}
                  </span>
                </div>
                <div>
                  <span className="font-medium text-foreground">Have:</span>{" "}
                  <span className="text-muted-foreground">
                    {comic.Have || 0}
                  </span>
                </div>
              </div>

              {/* Actions */}
              <div className="flex flex-wrap items-center gap-2 pt-4">
                <Button
                  onClick={handlePauseResume}
                  disabled={pauseMutation.isPending || resumeMutation.isPending}
                  variant="outline"
                  size="sm"
                >
                  {isPaused ? (
                    <>
                      <Play className="w-4 h-4 mr-2" />
                      Resume
                    </>
                  ) : (
                    <>
                      <Pause className="w-4 h-4 mr-2" />
                      Pause
                    </>
                  )}
                </Button>

                <Button
                  onClick={handleRefresh}
                  disabled={refreshMutation.isPending}
                  variant="outline"
                  size="sm"
                >
                  <RefreshCw
                    className={`w-4 h-4 mr-2 ${refreshMutation.isPending ? "animate-spin" : ""}`}
                  />
                  Refresh
                </Button>

                {!showDeleteConfirm ? (
                  <Button
                    onClick={() => setShowDeleteConfirm(true)}
                    variant="destructive"
                    size="sm"
                  >
                    <Trash2 className="w-4 h-4 mr-2" />
                    Delete
                  </Button>
                ) : (
                  <div className="flex items-center space-x-2">
                    <span className="text-sm text-red-600 font-medium">
                      Confirm delete?
                    </span>
                    <Button
                      onClick={handleDelete}
                      disabled={deleteMutation.isPending}
                      variant="destructive"
                      size="sm"
                    >
                      Yes, Delete
                    </Button>
                    <Button
                      onClick={() => setShowDeleteConfirm(false)}
                      variant="outline"
                      size="sm"
                    >
                      Cancel
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Issues/Chapters */}
      <div className="space-y-4">
        <h2 className="text-2xl font-bold">{itemLabel}</h2>
        <IssuesTable issues={issues} isManga={isManga} comicId={comicId} />
      </div>
    </div>
  );
}
