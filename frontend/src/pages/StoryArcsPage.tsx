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
import LibraryTabs, {
  useLibrarySummary,
} from "@/components/series/LibraryTabs";
import { Info } from "lucide-react";

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
  const summary = useLibrarySummary();

  return (
    <div className="page-transition flex h-full min-h-0 flex-col">
      <PageHeader title="Library" meta={summary} />
      <LibraryTabs />

      <div className="flex-1 min-h-0 overflow-auto px-8 py-4 space-y-5">
        <p className="flex items-start gap-2 text-[13px] text-foreground-2">
          <Info className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
          Story arcs are frozen for 1.0: they keep working, but get no new
          features. {count} arc{count === 1 ? "" : "s"} tracked.
        </p>
        {aiStatus?.configured && <ArcGenerator />}

        <ArcSearch searchInputRef={searchInputRef} formRef={searchFormRef} />

        {isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="rounded-lg border border-border bg-card overflow-hidden"
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
          <div className="border-t border-border-subtle">
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
