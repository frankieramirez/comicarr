import { ph, plural, t } from "@lingui/core/macro";
import { Badge } from "@/components/ui/badge";
import { CheckCircle2, XCircle } from "lucide-react";
import type { AiActivityEntry } from "@/hooks/useAiActivity";
import { formatDate, formatNumber } from "@/lib/intl";

// The feature name is the badge's text, so it needs no colour of its own. The
// six palette hues it used to carry had no dark-mode counterpart (DESIGN.md).
const FEATURE_BADGE_CLASS = "bg-muted text-muted-foreground";

function formatTimestamp(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    return formatDate(date, {
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
          <CheckCircle2 className="h-4 w-4 text-[var(--status-active)]" />
        ) : (
          <XCircle className="h-4 w-4 text-destructive" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <Badge className={FEATURE_BADGE_CLASS}>{entry.feature}</Badge>
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
            {plural(totalTokens, { one: "# token", other: "# tokens" })}
          </span>
          <span className="text-xs text-muted-foreground">
            {t`(${ph({ prompt: formatNumber(entry.prompt_tokens) })} prompt + ${ph({ completion: formatNumber(entry.completion_tokens) })} completion)`}
          </span>
        </div>
      </div>
    </div>
  );
}
