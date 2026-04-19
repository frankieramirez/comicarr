import { useRef } from "react";
import { useStoryArcs } from "@/hooks/useStoryArcs";
import { useAiStatus } from "@/hooks/useAiStatus";
import ArcSearch from "@/components/storyarcs/ArcSearch";
import ArcGenerator from "@/components/storyarcs/ArcGenerator";
import StoryArcCard from "@/components/storyarcs/StoryArcCard";
import StoryArcEmptyState from "@/components/storyarcs/StoryArcEmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import PageHeader from "@/components/layout/PageHeader";

export default function StoryArcsPage() {
  const { data: arcs, isLoading, error } = useStoryArcs();
  const { data: aiStatus } = useAiStatus();
  const searchInputRef = useRef<HTMLInputElement>(null);

  const handleSearchFocus = () => {
    searchInputRef.current?.focus();
  };

  const count = arcs?.length ?? 0;

  return (
    <div className="page-transition">
      <PageHeader
        title="Story Arcs"
        meta={
          isLoading
            ? "loading…"
            : `${count} arc${count === 1 ? "" : "s"} tracked`
        }
      />

      <div className="px-5 py-4 space-y-6">
        {aiStatus?.configured && <ArcGenerator />}

        <ArcSearch searchInputRef={searchInputRef} />

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
          <div className="py-12 text-center">
            <div className="font-mono text-[10px] tracking-[0.12em] uppercase text-muted-foreground mb-2">
              ARCS · ERROR
            </div>
            <div className="text-[15px] font-semibold">
              Failed to load story arcs
            </div>
            <div className="font-mono text-[11px] text-muted-foreground mt-1">
              {error.message}
            </div>
          </div>
        ) : arcs && arcs.length > 0 ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {arcs.map((arc) => (
              <StoryArcCard key={arc.StoryArcID} arc={arc} />
            ))}
          </div>
        ) : (
          <StoryArcEmptyState onSearchFocus={handleSearchFocus} />
        )}
      </div>
    </div>
  );
}
