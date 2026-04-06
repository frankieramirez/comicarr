import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

interface SuggestionCardProps {
  suggestion: {
    comic_name: string;
    publisher: string;
    reason: string;
    resolved_comic_id: string | null;
  };
  onAdd: (comicName: string, comicId?: string | null) => void;
}

export function SuggestionCard({ suggestion, onAdd }: SuggestionCardProps) {
  return (
    <div className="flex items-start justify-between gap-4 p-4 rounded-lg border border-card-border bg-card">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="font-medium text-sm truncate">
            {suggestion.comic_name}
          </span>
          <span className="text-xs text-muted-foreground shrink-0">
            {suggestion.publisher}
          </span>
        </div>
        <p className="text-xs text-muted-foreground line-clamp-2">
          {suggestion.reason}
        </p>
      </div>
      <Button
        variant="outline"
        size="sm"
        className="shrink-0"
        onClick={() =>
          onAdd(suggestion.comic_name, suggestion.resolved_comic_id)
        }
      >
        <Plus className="w-3.5 h-3.5 mr-1" />
        Add
      </Button>
    </div>
  );
}
