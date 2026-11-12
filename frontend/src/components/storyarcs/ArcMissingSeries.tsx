import { useState } from "react";
import { BookPlus, Loader2 } from "lucide-react";
import { SectionHeader } from "@/components/dashboard/DashboardPanel";
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
    <section aria-label="Missing from your library" className="mt-6 px-8">
      <SectionHeader
        title="Missing from your library"
        meta={`${missing.length} series · ${totalIssues} ${totalIssues === 1 ? "issue" : "issues"}`}
      />
      <div className="flex flex-col gap-3 rounded-md border border-border-subtle bg-surface-1 px-3 py-2 sm:flex-row sm:items-center">
        <p className="flex-1 text-[13px] text-foreground-2">
          This arc reads through series you don't track yet. Add them and
          Comicarr marks just the issues the arc needs as Wanted.
        </p>
        <Button
          type="button"
          variant="outline"
          size="toolbar"
          className="shrink-0 bg-surface-2"
          onClick={() => setConfirming(true)}
        >
          <BookPlus />
          Add what's missing
        </Button>
      </div>
      <div className="mt-1">
        {missing.map((series) => (
          <div
            key={series.comic_id || series.series_name}
            className="flex items-center justify-between gap-3 border-b border-border-subtle px-2 py-2 text-[13px]"
          >
            <span className="min-w-0 truncate">
              <span className="font-medium text-foreground">
                {series.series_name}
              </span>
              {series.series_year && (
                <span className="ml-1.5 text-foreground-2">
                  {series.series_year}
                </span>
              )}
              {series.issue_numbers.length > 0 && (
                <span className="mono-meta ml-2">
                  #{series.issue_numbers.join(", #")}
                </span>
              )}
            </span>
            <span className="shrink-0 text-foreground-2">
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
    </section>
  );
}
