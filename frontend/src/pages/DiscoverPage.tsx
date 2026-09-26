import { Bot, Compass, RefreshCw } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import EmptyState from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { useAiStatus } from "@/hooks/useAiStatus";
import {
  useAiRecommendations,
  useRefreshRecommendations,
} from "@/hooks/useAiRecommendations";
import { RecommendationCard } from "@/components/discover/RecommendationCard";

export default function DiscoverPage() {
  const { data: aiStatus } = useAiStatus();
  const aiConfigured = aiStatus?.configured ?? false;
  const {
    data: recommendations,
    isLoading,
    isError,
    refetch,
  } = useAiRecommendations(aiConfigured);
  const refresh = useRefreshRecommendations();

  const count = recommendations?.length ?? 0;
  const meta = aiConfigured
    ? isLoading
      ? "loading…"
      : `${count} recommendation${count === 1 ? "" : "s"}`
    : "AI not configured";

  const refreshButton = aiConfigured ? (
    <button
      type="button"
      onClick={() => void refresh.mutateAsync()}
      disabled={refresh.isPending}
      title="Regenerate recommendations from your library"
      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[5px] border text-[12px] font-medium disabled:opacity-50"
      style={{ borderColor: "var(--border)" }}
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
        {aiStatus === undefined || isLoading ? (
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
        ) : !aiConfigured ? (
          <EmptyState
            variant="custom"
            icon={Bot}
            eyebrow="DISCOVER · AI"
            title="Connect an AI provider"
            description="Comicarr can suggest series you might enjoy based on the library you already track. Configure an AI provider in Settings to enable recommendations."
            action={{ label: "AI settings", to: "/settings?tab=ai" }}
          />
        ) : isError ? (
          <div className="py-12 text-center">
            <div className="font-mono text-[10px] tracking-[0.12em] uppercase text-muted-foreground mb-2">
              DISCOVER · ERROR
            </div>
            <div className="text-[15px] font-semibold">
              Failed to load recommendations
            </div>
            <button
              type="button"
              onClick={() => void refetch()}
              className="mt-3 font-mono text-[11px] text-muted-foreground hover:text-foreground"
            >
              retry
            </button>
          </div>
        ) : recommendations && recommendations.length > 0 ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {recommendations.map((rec, index) => (
              <RecommendationCard
                key={`${rec.comicid ?? rec.comic_name}-${index}`}
                recommendation={rec}
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
              onClick: () => void refresh.mutateAsync(),
            }}
          />
        )}
      </div>
    </div>
  );
}
