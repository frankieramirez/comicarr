import { useRef } from "react";
import { useStoryArcs } from "@/hooks/useStoryArcs";
import { useAiStatus } from "@/hooks/useAiStatus";
import ArcSearch from "@/components/storyarcs/ArcSearch";
import ArcGenerator from "@/components/storyarcs/ArcGenerator";
import StoryArcCard from "@/components/storyarcs/StoryArcCard";
import StoryArcEmptyState from "@/components/storyarcs/StoryArcEmptyState";
import { Skeleton } from "@/components/ui/skeleton";

export default function StoryArcsPage() {
  const { data: arcs, isLoading, error } = useStoryArcs();
  const { data: aiStatus } = useAiStatus();
  const searchInputRef = useRef<HTMLInputElement>(null);

  const handleSearchFocus = () => {
    searchInputRef.current?.focus();
  };

  return (
    <div className="space-y-8 page-transition">
      <div>
        <h1 className="text-2xl font-bold text-foreground mb-1">Story Arcs</h1>
        <p className="text-sm text-muted-foreground">
          Track story arcs that span across multiple series.
        </p>
      </div>

      {/* AI Arc Generator (shown when AI configured) */}
      {aiStatus?.configured && <ArcGenerator />}

      {/* Search section */}
      <ArcSearch searchInputRef={searchInputRef} />

      {/* Arc list section */}
      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="rounded-lg border border-card-border bg-card overflow-hidden"
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
        <div className="text-center py-12">
          <p className="text-red-600">Failed to load story arcs</p>
          <p className="text-sm text-muted-foreground mt-1">{error.message}</p>
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
  );
}
