import { t } from "@lingui/core/macro";
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
      title={t`No story arcs tracked`}
      description={t`Search for story arcs above to add them to your watchlist. Track reading progress across multiple series and issues.`}
      action={
        onSearchFocus
          ? {
              label: t`Search Story Arcs`,
              onClick: onSearchFocus,
            }
          : undefined
      }
    />
  );
}
