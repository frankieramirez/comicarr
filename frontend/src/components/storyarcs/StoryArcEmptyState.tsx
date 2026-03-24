import { BookMarked } from "lucide-react";
import EmptyState from "@/components/ui/EmptyState";

interface StoryArcEmptyStateProps {
  onSearchFocus?: () => void;
}

export default function StoryArcEmptyState({
  onSearchFocus,
}: StoryArcEmptyStateProps) {
  return (
    <EmptyState
      icon={BookMarked}
      title="No story arcs tracked"
      description="Search for story arcs above to add them to your watchlist. Track reading progress across multiple series and issues."
      action={
        onSearchFocus
          ? {
              label: "Search Story Arcs",
              onClick: onSearchFocus,
            }
          : undefined
      }
    />
  );
}
