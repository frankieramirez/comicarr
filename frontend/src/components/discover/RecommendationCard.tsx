import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, Image as ImageIcon, Loader2, Plus } from "lucide-react";
import type { SeriesRecommendation } from "@/hooks/useAiRecommendations";
import { useAddComic } from "@/hooks/useSearch";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";

interface RecommendationCardProps {
  recommendation: SeriesRecommendation;
}

export function RecommendationCard({
  recommendation,
}: RecommendationCardProps) {
  const navigate = useNavigate();
  const addComicMutation = useAddComic();
  const { addToast } = useToast();
  const [isAdded, setIsAdded] = useState(false);

  const meta = [
    recommendation.comicyear,
    recommendation.publisher,
    recommendation.issues ? `${recommendation.issues} issues` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const handleAdd = async () => {
    if (!recommendation.comicid) {
      navigate(
        `/search?q=${encodeURIComponent(recommendation.comic_name)}&page=1`,
      );
      return;
    }

    try {
      await addComicMutation.mutateAsync(recommendation.comicid);
      setIsAdded(true);
      addToast({
        type: "success",
        title: "Adding Comic...",
        description: `${recommendation.comic_name} is being added to your library.`,
        duration: 5000,
      });
    } catch (err) {
      addToast({
        type: "error",
        title: "Failed to Add Series",
        description:
          err instanceof Error
            ? err.message
            : "An error occurred while adding the series.",
      });
    }
  };

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden flex flex-col">
      <div className="relative h-40 bg-muted overflow-hidden">
        {recommendation.comicimage ? (
          <img
            src={recommendation.comicimage}
            alt=""
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="flex items-center justify-center h-full">
            <ImageIcon className="w-10 h-10 text-muted-foreground/40" />
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/50 to-transparent" />
        {recommendation.because_of && (
          <div className="absolute bottom-2 left-2 right-2">
            <span className="inline-flex max-w-full items-center rounded-full bg-black/60 px-2 py-0.5 font-mono text-[10px] tracking-wider uppercase text-white truncate">
              Because you read {recommendation.because_of}
            </span>
          </div>
        )}
      </div>

      <div className="p-3 flex flex-1 flex-col">
        <h3 className="text-sm font-semibold text-foreground leading-tight line-clamp-2">
          {recommendation.comic_name}
        </h3>
        {meta && (
          <p className="mt-1 font-mono text-[10px] text-muted-foreground truncate">
            {meta}
          </p>
        )}
        <p className="mt-2 text-xs text-muted-foreground line-clamp-3 flex-1">
          {recommendation.reason}
        </p>
        <div className="mt-3 flex justify-end">
          <Button
            variant="outline"
            size="sm"
            disabled={isAdded || addComicMutation.isPending}
            onClick={() => void handleAdd()}
          >
            {isAdded ? (
              <>
                <Check className="w-3.5 h-3.5 mr-1" />
                Added
              </>
            ) : addComicMutation.isPending ? (
              <>
                <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />
                Adding…
              </>
            ) : (
              <>
                <Plus className="w-3.5 h-3.5 mr-1" />
                Add
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
