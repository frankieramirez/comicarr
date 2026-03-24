import { useState } from "react";
import { Plus, Check, Loader2, Image as ImageIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useAddStoryArc } from "@/hooks/useArcSearch";
import type { ArcSearchResult } from "@/types";

interface ArcSearchResultCardProps {
  result: ArcSearchResult;
}

export default function ArcSearchResultCard({
  result,
}: ArcSearchResultCardProps) {
  const { addToast } = useToast();
  const addMutation = useAddStoryArc();
  const [added, setAdded] = useState(!!result.haveit);

  const handleAdd = () => {
    if (added) return;

    addMutation.mutate(
      {
        arcid: result.cvarcid,
        storyarcname: result.name,
        storyarcissues: parseInt(result.issues, 10) || 0,
        arclist: result.arclist || "",
        cvarcid: result.cvarcid,
      },
      {
        onSuccess: () => {
          setAdded(true);
          addToast({
            type: "success",
            title: "Arc Added",
            description: `Adding ${result.name}...`,
          });
        },
        onError: () => {
          addToast({
            type: "error",
            title: "Error",
            description: "Failed to add story arc.",
          });
        },
      },
    );
  };

  return (
    <div className="rounded-lg border border-card-border bg-card overflow-hidden">
      {/* Image */}
      <div className="h-24 bg-muted overflow-hidden">
        {result.image ? (
          <img
            src={result.image}
            alt={result.name}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="flex items-center justify-center h-full">
            <ImageIcon className="w-8 h-8 text-muted-foreground/40" />
          </div>
        )}
      </div>

      {/* Content */}
      <div className="p-3">
        <h4 className="text-sm font-semibold text-foreground line-clamp-1">
          {result.name}
        </h4>
        <div className="flex items-center gap-2 text-xs text-muted-foreground mt-1">
          {result.publisher && <span>{result.publisher}</span>}
          <span>{result.issues} issues</span>
        </div>

        {result.description && (
          <p className="text-xs text-muted-foreground mt-2 line-clamp-2">
            {result.description.replace(/<[^>]*>/g, "")}
          </p>
        )}

        <div className="mt-3">
          {added ? (
            <Button variant="outline" size="sm" className="w-full" disabled>
              <Check className="w-4 h-4 mr-1" />
              Added
            </Button>
          ) : (
            <Button
              variant="default"
              size="sm"
              className="w-full"
              onClick={handleAdd}
              disabled={addMutation.isPending}
            >
              {addMutation.isPending ? (
                <Loader2 className="w-4 h-4 mr-1 animate-spin" />
              ) : (
                <Plus className="w-4 h-4 mr-1" />
              )}
              Add Arc
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
