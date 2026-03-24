import { useParams, Link } from "react-router-dom";
import { ChevronRight, BookMarked } from "lucide-react";
import { useStoryArcDetail } from "@/hooks/useStoryArcs";
import ArcHeader from "@/components/storyarcs/ArcHeader";
import ArcIssueTable from "@/components/storyarcs/ArcIssueTable";
import { Skeleton } from "@/components/ui/skeleton";

export default function StoryArcDetailPage() {
  const { storyArcId } = useParams<{ storyArcId: string }>();
  const { data, isLoading, error } = useStoryArcDetail(storyArcId);

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full rounded-lg" />
        <Skeleton className="h-64 w-full rounded-lg" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="text-center py-12">
        <p className="text-red-600 text-lg">Failed to load story arc</p>
        <p className="text-muted-foreground text-sm mt-2">
          {error?.message || "Story arc not found"}
        </p>
        <Link
          to="/story-arcs"
          className="text-primary text-sm mt-4 inline-block hover:underline"
        >
          Back to Story Arcs
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6 page-transition">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1 text-sm text-muted-foreground">
        <Link
          to="/story-arcs"
          className="hover:text-foreground transition-colors flex items-center gap-1"
        >
          <BookMarked className="w-4 h-4" />
          Story Arcs
        </Link>
        <ChevronRight className="w-4 h-4" />
        <span className="text-foreground font-medium">{data.arc.StoryArc}</span>
      </nav>

      {/* Arc header with banner, stats, actions */}
      <ArcHeader arc={data.arc} />

      {/* Issues table */}
      {data.issues.length > 0 ? (
        <ArcIssueTable issues={data.issues} storyArcId={data.arc.StoryArcID} />
      ) : (
        <div className="text-center py-12 text-muted-foreground">
          <p>No issues in this arc yet.</p>
        </div>
      )}
    </div>
  );
}
