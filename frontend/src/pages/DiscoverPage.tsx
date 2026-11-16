import { plural, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Bot, Compass, RefreshCw } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import PageShell from "@/components/layout/PageShell";
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
        title: t`Failed to refresh recommendations`,
        description:
          error instanceof Error ? error.message : t`Please try again.`,
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
          title: t`Failed to add series`,
          description: detail.message || t`Please try again.`,
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
      ? t`unavailable`
      : refresh.isPending
        ? t`generating…`
        : aiConfigured
          ? isLoading
            ? t`loading…`
            : plural(count, {
                one: "# recommendation",
                other: "# recommendations",
              })
          : t`AI not configured`;

  const refreshButton = aiConfigured ? (
    <button
      type="button"
      onClick={() => void handleRefresh()}
      disabled={refresh.isPending}
      title={t`Regenerate recommendations from your library`}
      className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium disabled:opacity-50"
    >
      <RefreshCw
        className={`w-3.5 h-3.5 ${refresh.isPending ? "animate-spin" : ""}`}
      />
      {refresh.isPending ? t`Refreshing…` : t`Refresh`}
    </button>
  ) : null;

  return (
    <PageShell
      header={
        <PageHeader title={t`Discover`} meta={meta} actions={refreshButton} />
      }
    >
      <div className="px-5 py-4">
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
            <div className="mono-label mb-2">
              <Trans>DISCOVER · ERROR</Trans>
            </div>
            <div className="text-base font-semibold">
              <Trans>Failed to check AI status</Trans>
            </div>
            <button
              type="button"
              onClick={() => void retryStatus()}
              className="mt-3 text-xs text-muted-foreground hover:text-foreground"
            >
              <Trans>Retry</Trans>
            </button>
          </div>
        ) : !aiConfigured ? (
          <EmptyState
            variant="custom"
            icon={Bot}
            eyebrow={t`DISCOVER · AI`}
            title={t`Connect an AI provider`}
            description={t`Comicarr can suggest series you might enjoy based on the library you already track. Configure an AI provider in Settings to enable recommendations.`}
            action={{ label: t`AI settings`, to: "/settings?tab=ai" }}
          />
        ) : refresh.isPending ? (
          <EmptyState
            variant="custom"
            icon={Bot}
            eyebrow={t`DISCOVER · AI`}
            title={t`Generating recommendations`}
            description={t`Looking for series that fit your library.`}
          />
        ) : refresh.isError || isError ? (
          <div className="py-12 text-center" role="alert">
            <div className="mono-label mb-2">
              <Trans>DISCOVER · ERROR</Trans>
            </div>
            <div className="text-base font-semibold">
              {refresh.isError
                ? t`Failed to refresh recommendations`
                : t`Failed to load recommendations`}
            </div>
            <button
              type="button"
              onClick={() =>
                void (refresh.isError ? handleRefresh() : refetch())
              }
              disabled={refresh.isPending}
              className="mt-3 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
            >
              <Trans>Retry</Trans>
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
            eyebrow={t`DISCOVER · EMPTY`}
            title={t`No recommendations yet`}
            description={t`Recommendations refresh with the weekly pull list, or on demand.`}
            action={{
              label: t`Generate recommendations`,
              onClick: () => void handleRefresh(),
            }}
          />
        )}
      </div>
    </PageShell>
  );
}
