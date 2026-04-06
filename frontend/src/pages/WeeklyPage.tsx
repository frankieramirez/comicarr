import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";
import { Calendar } from "lucide-react";
import { useAiStatus } from "@/hooks/useAiStatus";
import { AiSuggestions } from "@/components/weekly/AiSuggestions";
import { Skeleton } from "@/components/ui/skeleton";
import ErrorDisplay from "@/components/ui/ErrorDisplay";

interface WeeklyIssue {
  COMIC: string;
  ISSUE: string;
  PUBLISHER: string;
  SHIPDATE: string;
  STATUS: string;
  ComicID: string;
}

function useWeeklyPullList() {
  return useQuery({
    queryKey: ["weekly"],
    queryFn: () => apiRequest<WeeklyIssue[]>("GET", "/api/weekly"),
    staleTime: 5 * 60 * 1000,
  });
}

export default function WeeklyPage() {
  const { data: weekly, isLoading, error } = useWeeklyPullList();
  const { data: aiStatus } = useAiStatus();

  if (error) {
    return (
      <ErrorDisplay
        error={error}
        title="Unable to load weekly pull list"
        onRetry={() => window.location.reload()}
      />
    );
  }

  return (
    <div className="page-transition">
      <div className="flex items-center gap-3 mb-8">
        <Calendar className="w-6 h-6 text-muted-foreground" />
        <div>
          <h1 className="text-[32px] font-bold tracking-tight">
            Weekly Pull List
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            This week&apos;s new releases
          </p>
        </div>
      </div>

      {aiStatus?.configured && (
        <div className="mb-8">
          <AiSuggestions />
        </div>
      )}

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 10 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : !weekly || weekly.length === 0 ? (
        <div className="rounded-lg border border-card-border bg-card p-8 text-center">
          <p className="text-muted-foreground">
            No pull list data available. Run a weekly pull list update from
            Settings.
          </p>
        </div>
      ) : (
        <div className="rounded-lg border border-card-border overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-card-border bg-muted/50">
                <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
                  Title
                </th>
                <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
                  Issue
                </th>
                <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
                  Publisher
                </th>
                <th className="text-left text-xs font-medium text-muted-foreground px-4 py-3">
                  Status
                </th>
              </tr>
            </thead>
            <tbody>
              {weekly.map((issue, index) => (
                <tr
                  key={`${issue.COMIC}-${issue.ISSUE}-${index}`}
                  className="border-b border-card-border last:border-0 hover:bg-muted/30"
                >
                  <td className="px-4 py-2.5 text-sm font-medium">
                    {issue.COMIC}
                  </td>
                  <td className="px-4 py-2.5 text-sm text-muted-foreground">
                    #{issue.ISSUE}
                  </td>
                  <td className="px-4 py-2.5 text-sm text-muted-foreground">
                    {issue.PUBLISHER}
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full ${
                        issue.STATUS === "Wanted"
                          ? "bg-yellow-500/10 text-yellow-600"
                          : issue.STATUS === "Downloaded"
                            ? "bg-green-500/10 text-green-600"
                            : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {issue.STATUS || "Available"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
