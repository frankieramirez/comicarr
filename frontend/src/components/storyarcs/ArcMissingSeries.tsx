import { useState } from "react";
import { BookPlus, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import {
  useAddMissingArcSeries,
  useArcMissingSeries,
} from "@/hooks/useStoryArcs";
import type { MissingArcSeries } from "@/types";

interface ArcMissingSeriesProps {
  storyArcId: string;
  missing: MissingArcSeries[];
}

export default function ArcMissingSeries({
  storyArcId,
  missing,
}: ArcMissingSeriesProps) {
  const [confirming, setConfirming] = useState(false);
  const { addToast } = useToast();
  const preview = useArcMissingSeries(storyArcId, confirming);
  const addMissing = useAddMissingArcSeries();

  const resolved = (preview.data?.series ?? []).filter(
    (series) => series.match !== null,
  );

  const totalIssues = missing.reduce((sum, s) => sum + s.issue_count, 0);

  const handleConfirm = () => {
    addMissing.mutate(
      {
        storyArcId,
        additions: resolved.map((series) => ({
          series_name: series.series_name,
          comic_id: series.match!.comic_id,
        })),
      },
      {
        onSuccess: (data) => {
          setConfirming(false);
          addToast({
            type: "success",
            title: "Adding Series",
            description: `Adding ${data.queued ?? resolved.length} series — the arc's issues will be marked Wanted as they import.`,
          });
        },
        onError: () => {
          addToast({
            type: "error",
            title: "Error",
            description: "Failed to queue the missing series.",
          });
        },
      },
    );
  };

  return (
    <div className="rounded-lg border border-card-border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BookPlus className="w-4 h-4 text-primary" />
          <h3 className="text-sm font-medium text-foreground">
            Missing from your library
          </h3>
        </div>
        <Button size="sm" onClick={() => setConfirming(true)}>
          Add what's missing
        </Button>
      </div>

      <div className="divide-y divide-border rounded-md border border-border">
        {missing.map((series) => (
          <div
            key={series.comic_id || series.series_name}
            className="flex items-center justify-between px-3 py-2 text-sm"
          >
            <span className="font-medium text-foreground truncate">
              {series.series_name}
              {series.series_year && (
                <span className="text-muted-foreground ml-1">
                  ({series.series_year})
                </span>
              )}
            </span>
            <span className="text-muted-foreground shrink-0 ml-3">
              needs {series.issue_count}{" "}
              {series.issue_count === 1 ? "issue" : "issues"}
            </span>
          </div>
        ))}
      </div>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Add what's missing</DialogTitle>
            <DialogDescription>
              These series will be added to your library, and the {totalIssues}{" "}
              issue{totalIssues !== 1 ? "s" : ""} this arc needs will be marked
              Wanted — the rest of each series is left alone.
            </DialogDescription>
          </DialogHeader>

          {preview.isPending && (
            <div className="flex items-center gap-2 py-6 justify-center text-sm text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin" />
              Matching series on ComicVine...
            </div>
          )}

          {preview.isError && (
            <p className="text-sm text-destructive py-4">
              Could not look up the missing series. Try again.
            </p>
          )}

          {preview.isSuccess && (
            <div className="divide-y divide-border rounded-md border border-border max-h-72 overflow-auto">
              {preview.data.series.map((series) => (
                <div
                  key={series.comic_id || series.series_name}
                  className="flex items-center gap-3 px-3 py-2 text-sm"
                >
                  <div className="flex-1 min-w-0">
                    {series.match ? (
                      <>
                        <span className="font-medium text-foreground">
                          {series.match.name || series.series_name}
                        </span>
                        <span className="text-muted-foreground ml-1.5">
                          {[series.match.year, series.match.publisher]
                            .filter(Boolean)
                            .join(" · ")}
                        </span>
                        <p className="text-xs text-muted-foreground truncate">
                          {series.series_name} —{" "}
                          {series.issue_numbers.join(", ")}
                        </p>
                      </>
                    ) : (
                      <>
                        <span className="font-medium text-foreground">
                          {series.series_name}
                        </span>
                        <p className="text-xs text-muted-foreground">
                          No ComicVine match — won't be added
                        </p>
                      </>
                    )}
                  </div>
                  <span className="text-muted-foreground shrink-0">
                    {series.issue_count}{" "}
                    {series.issue_count === 1 ? "issue" : "issues"}
                  </span>
                </div>
              ))}
            </div>
          )}

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirming(false)}
              disabled={addMissing.isPending}
            >
              Cancel
            </Button>
            <Button
              onClick={handleConfirm}
              disabled={
                addMissing.isPending ||
                !preview.isSuccess ||
                resolved.length === 0
              }
            >
              {addMissing.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                  Adding...
                </>
              ) : (
                `Add ${resolved.length} series & mark issues Wanted`
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
