import { useNavigate } from "react-router-dom";
import { Sparkles } from "lucide-react";
import {
  useAiSuggestions,
  type PullSuggestion,
} from "@/hooks/useAiSuggestions";
import { SuggestionCard } from "./SuggestionCard";
import { Skeleton } from "@/components/ui/skeleton";

export function AiSuggestions() {
  const { data: suggestions, isLoading } = useAiSuggestions();
  const navigate = useNavigate();

  const handleAdd = (comicName: string, comicId?: string | null) => {
    if (comicId) {
      navigate(`/search?q=${encodeURIComponent(comicName)}&page=1`);
    } else {
      navigate(`/search?q=${encodeURIComponent(comicName)}&page=1`);
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }

  if (!suggestions || suggestions.length === 0) {
    return (
      <div className="rounded-lg border border-card-border bg-card p-6 text-center">
        <Sparkles className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
        <p className="text-sm text-muted-foreground">
          Nothing new this week matches your collection
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Sparkles className="w-4 h-4 text-muted-foreground" />
        <h3 className="text-sm font-semibold">Suggested For You</h3>
      </div>
      <div className="space-y-2">
        {suggestions.map((suggestion: PullSuggestion, index: number) => (
          <SuggestionCard
            key={`${suggestion.comic_name}-${index}`}
            suggestion={suggestion}
            onAdd={handleAdd}
          />
        ))}
      </div>
    </div>
  );
}
