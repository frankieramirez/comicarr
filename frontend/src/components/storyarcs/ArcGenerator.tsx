import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import { Sparkles, Loader2, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import ArcIssueRow from "./ArcIssueRow";

interface GeneratedIssue {
  series_name: string;
  issue_number: string;
  title: string | null;
  reading_order: number;
  comic_id: string | null;
  issue_id: string | null;
  verified: boolean;
  library_status: "owned" | "wanted" | "not_tracked";
}

interface GenerateResponse {
  success: boolean;
  issues: GeneratedIssue[];
  description?: string;
  error?: string;
}

interface SaveResponse {
  success: boolean;
  arc_id?: string;
  error?: string;
}

export default function ArcGenerator() {
  const [description, setDescription] = useState("");
  const [generatedIssues, setGeneratedIssues] = useState<GeneratedIssue[]>([]);
  const [arcDescription, setArcDescription] = useState("");
  const queryClient = useQueryClient();

  const generateMutation = useMutation({
    mutationFn: (desc: string) =>
      apiRequest<GenerateResponse>("POST", "/api/storyarcs/generate", {
        description: desc,
      }),
    onSuccess: (data) => {
      if (data.success && data.issues) {
        setGeneratedIssues(data.issues);
        setArcDescription(data.description || description);
      }
    },
  });

  const saveMutation = useMutation({
    mutationFn: (params: { arc_name: string; issues: GeneratedIssue[] }) =>
      apiRequest<SaveResponse>("POST", "/api/storyarcs/generate/save", {
        arc_name: params.arc_name,
        issues: params.issues,
      }),
    onSuccess: (data) => {
      if (data.success) {
        setGeneratedIssues([]);
        setDescription("");
        setArcDescription("");
        queryClient.invalidateQueries({ queryKey: ["storyArcs"] });
      }
    },
  });

  const handleGenerate = () => {
    const trimmed = description.trim();
    if (trimmed.length < 3) return;
    generateMutation.mutate(trimmed);
  };

  const handleSave = () => {
    if (!generatedIssues.length || !arcDescription) return;
    saveMutation.mutate({ arc_name: arcDescription, issues: generatedIssues });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleGenerate();
    }
  };

  return (
    <div className="rounded-lg border border-card-border bg-card p-4 space-y-4">
      <div className="flex items-center gap-2">
        <Sparkles className="w-4 h-4 text-primary" />
        <h3 className="text-sm font-medium text-foreground">
          AI Reading Order Generator
        </h3>
      </div>

      <div className="flex gap-2">
        <Input
          type="text"
          placeholder="e.g. Dark Phoenix Saga, Secret Wars 2015, Spider-Verse..."
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={generateMutation.isPending}
          className="flex-1"
        />
        <Button
          onClick={handleGenerate}
          disabled={description.trim().length < 3 || generateMutation.isPending}
          size="sm"
        >
          {generateMutation.isPending ? (
            <>
              <Loader2 className="w-4 h-4 mr-1 animate-spin" />
              Generating...
            </>
          ) : (
            "Generate"
          )}
        </Button>
      </div>

      {generateMutation.isError && (
        <p className="text-sm text-destructive">
          {generateMutation.error?.message ||
            "Failed to generate reading order"}
        </p>
      )}

      {!generateMutation.isPending &&
        generateMutation.isSuccess &&
        generatedIssues.length === 0 && (
          <p className="text-sm text-muted-foreground text-center py-4">
            No issues found for this arc. Try a more specific description.
          </p>
        )}

      {generatedIssues.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              {generatedIssues.length} issues in reading order
            </p>
            <Button
              onClick={handleSave}
              disabled={saveMutation.isPending}
              size="sm"
              variant="default"
            >
              {saveMutation.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Save className="w-4 h-4 mr-1" />
                  Save Arc
                </>
              )}
            </Button>
          </div>

          {saveMutation.isError && (
            <p className="text-sm text-destructive">
              {saveMutation.error?.message || "Failed to save arc"}
            </p>
          )}

          {saveMutation.isSuccess && (
            <p className="text-sm text-green-600 dark:text-green-400">
              Story arc saved successfully.
            </p>
          )}

          <div className="rounded-md border border-border divide-y divide-border">
            {generatedIssues.map((issue) => (
              <ArcIssueRow
                key={`${issue.series_name}-${issue.issue_number}-${issue.reading_order}`}
                issue={issue}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
