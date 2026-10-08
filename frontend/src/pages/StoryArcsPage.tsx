import { useRef } from "react";
import { useStoryArcs } from "@/hooks/useStoryArcs";
import { useAiStatus } from "@/hooks/useAiStatus";
import ArcSearch from "@/components/storyarcs/ArcSearch";
import ArcGenerator from "@/components/storyarcs/ArcGenerator";
import StoryArcCard from "@/components/storyarcs/StoryArcCard";
import StoryArcEmptyState from "@/components/storyarcs/StoryArcEmptyState";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import { Skeleton } from "@/components/ui/skeleton";
import PageHeader from "@/components/layout/PageHeader";

export default function StoryArcsPage() {
  const { data: arcs, isLoading, error, refetch, isFetching } = useStoryArcs();
  const { data: aiStatus } = useAiStatus();
  const searchInputRef = useRef<HTMLInputElement>(null);
  const searchFormRef = useRef<HTMLFormElement>(null);

  const handleSearchAction = () => {
    searchInputRef.current?.focus();
    searchFormRef.current?.requestSubmit();
  };

  const count = arcs?.length ?? 0;

  return (
    <div className="page-transition flex h-full min-h-0 flex-col">
      <PageHeader
        title="Story Arcs"
        meta={
          isLoading
            ? "loading…"
            : `${count} arc${count === 1 ? "" : "s"} tracked`
        }
      />

      <div className="flex-1 min-h-0 overflow-auto px-5 py-4 space-y-6">
        {aiStatus?.configured && <ArcGenerator />}

        <ArcSearch searchInputRef={searchInputRef} formRef={searchFormRef} />

        {isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="rounded-[6px] border border-border bg-card overflow-hidden"
              >
                <Skeleton className="h-32" />
                <div className="p-3 space-y-2">
                  <Skeleton className="h-4 w-3/4" />
                  <Skeleton className="h-3 w-1/2" />
                  <Skeleton className="h-1.5 w-full" />
                </div>
              </div>
            ))}
          </div>
        ) : error ? (
          <ErrorDisplay
            error={error}
            title="Unable to load story arcs"
            onRetry={() => {
              void refetch();
            }}
            isRetrying={isFetching}
          />
        ) : arcs && arcs.length > 0 ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {arcs.map((arc) => (
              <StoryArcCard key={arc.StoryArcID} arc={arc} />
            ))}
          </div>
        ) : (
          <StoryArcEmptyState onSearchFocus={handleSearchAction} />
        )}
      </div>
    </div>
  );
}
