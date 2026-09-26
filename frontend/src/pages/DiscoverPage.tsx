import { useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Bot, Compass, RefreshCw } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import EmptyState from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { useAiStatus } from "@/hooks/useAiStatus";
import {
  type SeriesRecommendation,
  removeRecommendation,
  restoreRecommendation,
  useAiRecommendations,
  useRefreshRecommendations,
} from "@/hooks/useAiRecommendations";
import { RecommendationCard } from "@/components/discover/RecommendationCard";
import type { ComicAddedDetail } from "@/types/events";

export default function DiscoverPage() {
  const queryClient = useQueryClient();
  const { addToast } = useToast();
  const {
    data: aiStatus,
    isLoading: statusLoading,
    isError: statusError,
    refetch: retryStatus,
  } = useAiStatus();
  const aiConfigured = aiStatus?.configured ?? false;
  const {
    data: recommendations,
    isLoading,
    isError,
    refetch,
  } = useAiRecommendations(aiConfigured);
  const refresh = useRefreshRecommendations();
  const refreshInFlight = useRef(false);
  const queued = useRef(new Map<string, SeriesRecommendation>());

  const handleRefresh = useCallback(async () => {
    if (refreshInFlight.current || refresh.isPending) return;
    refreshInFlight.current = true;
    refresh.reset();
    try {
      await refresh.mutateAsync();
    } catch (error) {
      addToast({
        type: "error",
        title: "Failed to refresh recommendations",
        description:
          error instanceof Error ? error.message : "Please try again.",
      });
    } finally {
      refreshInFlight.current = false;
    }
  }, [refresh, addToast]);

  const handleQueued = useCallback(
    (recommendation: SeriesRecommendation, comicId: string) => {
      queued.current.set(comicId, recommendation);
      removeRecommendation(queryClient, recommendation.comicid ?? comicId);
    },
    [queryClient],
  );

  useEffect(() => {
    const pending = queued.current;
    const handleAdded = (event: Event) => {
      let detail: ComicAddedDetail;
      try {
        detail = JSON.parse((event as CustomEvent<string>).detail);
      } catch {
        return;
      }
      const recommendation = pending.get(detail.comicid);
      if (!recommendation) return;
      pending.delete(detail.comicid);
      if (detail.status === "failure") {
        restoreRecommendation(queryClient, recommendation);
        addToast({
          type: "error",
          title: "Failed to add series",
          description: detail.message || "Please try again.",
        });
      }
    };
    window.addEventListener("comic-added", handleAdded);
    return () => {
      window.removeEventListener("comic-added", handleAdded);
      if (pending.size > 0) {
        void queryClient.invalidateQueries({
          queryKey: ["ai", "recommendations"],
        });
      }
    };
  }, [queryClient, addToast]);

  const count = recommendations?.length ?? 0;
  const meta =
    statusError || refresh.isError || isError
      ? "unavailable"
      : refresh.isPending
        ? "generating…"
        : aiConfigured
          ? isLoading
            ? "loading…"
            : `${count} recommendation${count === 1 ? "" : "s"}`
          : "AI not configured";

  const refreshButton = aiConfigured ? (
    <button
      type="button"
      onClick={() => void handleRefresh()}
      disabled={refresh.isPending}
      title="Regenerate recommendations from your library"
      className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium disabled:opacity-50"
    >
      <RefreshCw
        className={`w-3.5 h-3.5 ${refresh.isPending ? "animate-spin" : ""}`}
      />
      {refresh.isPending ? "Refreshing…" : "Refresh"}
    </button>
  ) : null;

  return (
    <div className="page-transition flex h-full min-h-0 flex-col">
      <PageHeader title="Discover" meta={meta} actions={refreshButton} />

      <div className="flex-1 min-h-0 overflow-auto px-5 py-4">
        {statusLoading || (aiConfigured && isLoading && !refresh.isError) ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="rounded-lg border border-border bg-card overflow-hidden"
              >
                <Skeleton className="h-40" />
                <div className="p-3 space-y-2">
                  <Skeleton className="h-4 w-3/4" />
                  <Skeleton className="h-3 w-1/2" />
                  <Skeleton className="h-3 w-full" />
                </div>
              </div>
            ))}
          </div>
        ) : statusError ? (
          <div className="py-12 text-center" role="alert">
            <div className="mono-label mb-2">DISCOVER · ERROR</div>
            <div className="text-base font-semibold">
              Failed to check AI status
            </div>
            <button
              type="button"
              onClick={() => void retryStatus()}
              className="mt-3 text-xs text-muted-foreground hover:text-foreground"
            >
              Retry
            </button>
          </div>
        ) : !aiConfigured ? (
          <EmptyState
            variant="custom"
            icon={Bot}
            eyebrow="DISCOVER · AI"
            title="Connect an AI provider"
            description="Comicarr can suggest series you might enjoy based on the library you already track. Configure an AI provider in Settings to enable recommendations."
            action={{ label: "AI settings", to: "/settings?tab=ai" }}
          />
        ) : refresh.isPending ? (
          <EmptyState
            variant="custom"
            icon={Bot}
            eyebrow="DISCOVER · AI"
            title="Generating recommendations"
            description="Looking for series that fit your library."
          />
        ) : refresh.isError || isError ? (
          <div className="py-12 text-center" role="alert">
            <div className="mono-label mb-2">DISCOVER · ERROR</div>
            <div className="text-base font-semibold">
              {refresh.isError
                ? "Failed to refresh recommendations"
                : "Failed to load recommendations"}
            </div>
            <button
              type="button"
              onClick={() =>
                void (refresh.isError ? handleRefresh() : refetch())
              }
              disabled={refresh.isPending}
              className="mt-3 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
            >
              Retry
            </button>
          </div>
        ) : recommendations && recommendations.length > 0 ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {recommendations.map((rec, index) => (
              <RecommendationCard
                key={`${rec.comicid ?? rec.comic_name}-${index}`}
                recommendation={rec}
                onQueued={handleQueued}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            variant="custom"
            icon={Compass}
            eyebrow="DISCOVER · EMPTY"
            title="No recommendations yet"
            description="Recommendations refresh with the weekly pull list, or on demand."
            action={{
              label: "Generate recommendations",
              onClick: () => void handleRefresh(),
            }}
          />
        )}
      </div>
    </div>
  );
}
