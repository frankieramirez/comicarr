import { Badge } from "@/components/ui/badge";
import { CheckCircle2, XCircle } from "lucide-react";
import type { AiActivityEntry } from "@/hooks/useAiActivity";

const FEATURE_COLORS: Record<string, string> = {
  parsing: "bg-blue-500/15 text-blue-400",
  search: "bg-green-500/15 text-green-400",
  enrichment: "bg-purple-500/15 text-purple-400",
  reconciliation: "bg-amber-500/15 text-amber-400",
  chat: "bg-cyan-500/15 text-cyan-400",
  curation: "bg-rose-500/15 text-rose-400",
};

function getFeatureBadgeClass(feature: string): string {
  return FEATURE_COLORS[feature] || "bg-muted text-muted-foreground";
}

function formatTimestamp(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return timestamp;
  }
}

interface ActivityFeedEntryProps {
  entry: AiActivityEntry;
}

export function ActivityFeedEntry({ entry }: ActivityFeedEntryProps) {
  const totalTokens = entry.prompt_tokens + entry.completion_tokens;

  return (
    <div className="flex items-start gap-3 py-3 px-4 border-b border-border last:border-b-0">
      <div className="flex-shrink-0 mt-0.5">
        {entry.success ? (
          <CheckCircle2 className="h-4 w-4 text-green-400" />
        ) : (
          <XCircle className="h-4 w-4 text-destructive" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <Badge className={getFeatureBadgeClass(entry.feature)}>
            {entry.feature}
          </Badge>
          <span className="text-xs text-muted-foreground">
            {formatTimestamp(entry.timestamp)}
          </span>
        </div>
        <p className="text-sm text-foreground truncate">{entry.action}</p>
        {!entry.success && entry.error_message && (
          <p className="text-xs text-destructive mt-1">{entry.error_message}</p>
        )}
        <div className="flex items-center gap-2 mt-1">
          <span className="text-xs text-muted-foreground">
            {totalTokens.toLocaleString()} tokens
          </span>
          <span className="text-xs text-muted-foreground">
            ({entry.prompt_tokens.toLocaleString()} prompt +{" "}
            {entry.completion_tokens.toLocaleString()} completion)
          </span>
        </div>
      </div>
    </div>
  );
}
