import { useParams, Link } from "react-router-dom";
import { BookMarked } from "lucide-react";
import { useStoryArcDetail } from "@/hooks/useStoryArcs";
import ArcHeader from "@/components/storyarcs/ArcHeader";
import ArcIssueTable from "@/components/storyarcs/ArcIssueTable";
import ArcMissingSeries from "@/components/storyarcs/ArcMissingSeries";
import { SectionHeader } from "@/components/dashboard/DashboardPanel";
import { buttonVariants } from "@/components/ui/button";
import EmptyState from "@/components/ui/EmptyState";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import { Skeleton } from "@/components/ui/skeleton";
import { isNotFoundError } from "@/lib/api";

export default function StoryArcDetailPage() {
  const { storyArcId } = useParams<{ storyArcId: string }>();
  const { data, isLoading, error, refetch, isFetching } =
    useStoryArcDetail(storyArcId);

  if (isLoading) {
    return (
      <div className="space-y-5 px-8 pt-5">
        <h1 className="sr-only">Story arc</h1>
        <Skeleton className="h-4 w-48" />
        <div className="flex gap-5">
          <Skeleton className="aspect-[2/3] w-24 rounded-md" />
          <div className="flex-1 space-y-3 pt-1">
            <Skeleton className="h-8 w-1/2" />
            <Skeleton className="h-4 w-1/3" />
          </div>
        </div>
        <Skeleton className="h-64 w-full rounded-md" />
      </div>
    );
  }

  if (error && !isNotFoundError(error)) {
    return (
      <div className="px-8 pt-5">
        <ErrorDisplay
          error={error}
          title="Unable to load story arc"
          onRetry={() => {
            void refetch();
          }}
          isRetrying={isFetching}
        />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="px-8">
        <div className="mx-auto max-w-lg py-16 text-center">
          <h1 className="text-lg font-semibold">Story arc not found</h1>
          <p className="mt-2 text-sm text-foreground-2">
            {error?.message || "Story arc not found"}
          </p>
          <Link
            to="/story-arcs"
            className={buttonVariants({
              variant: "outline",
              size: "toolbar",
              className: "mt-6",
            })}
          >
            Back to story arcs
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto overflow-x-hidden pb-8 page-transition">
      <ArcHeader arc={data.arc} />

      {data.missing.length > 0 && (
        <ArcMissingSeries
          storyArcId={data.arc.StoryArcID}
          missing={data.missing}
        />
      )}

      <section aria-label="Reading order" className="mt-6">
        <div className="px-8">
          <SectionHeader
            title="Reading order"
            meta={`${data.issues.length} ${data.issues.length === 1 ? "issue" : "issues"}`}
          />
        </div>
        {data.issues.length > 0 ? (
          <ArcIssueTable
            issues={data.issues}
            storyArcId={data.arc.StoryArcID}
          />
        ) : (
          <EmptyState
            variant="custom"
            icon={BookMarked}
            eyebrow="ARC · EMPTY"
            title="No issues in this arc yet"
            description="Refresh the arc to pull its reading order from ComicVine."
          />
        )}
      </section>
    </div>
  );
}
