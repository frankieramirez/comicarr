import { Bot, CheckCircle, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface AiActivity {
  timestamp: string;
  feature_type: string;
  action_description: string;
  prompt_tokens: number;
  completion_tokens: number;
  success: boolean;
}

interface AiInsightsPanelProps {
  activity?: AiActivity[];
}

function formatTimestamp(ts: string): string {
  if (!ts) return "";
  try {
    const date = new Date(ts);
    return date.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

export default function AiInsightsPanel({ activity }: AiInsightsPanelProps) {
  const items = activity ?? [];

  return (
    <Card className="mt-6">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Bot className="w-4 h-4" />
          AI Activity
        </CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">
            No AI activity yet. AI features will appear here as you use them.
          </p>
        ) : (
          <div className="space-y-3">
            {items.map((item, idx) => (
              <div
                key={`${item.timestamp}-${idx}`}
                className="flex items-start gap-3 rounded-lg p-2 -mx-2"
              >
                {item.success ? (
                  <CheckCircle className="w-4 h-4 mt-0.5 text-[var(--status-active)] shrink-0" />
                ) : (
                  <XCircle className="w-4 h-4 mt-0.5 text-[var(--status-error)] shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                  <p className="text-sm">{item.action_description}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {formatTimestamp(item.timestamp)}
                    {item.prompt_tokens > 0 &&
                      ` \u00B7 ${item.prompt_tokens + item.completion_tokens} tokens`}
                  </p>
                </div>
                <Badge variant="secondary" className="text-[10px] shrink-0">
                  {item.feature_type}
                </Badge>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
