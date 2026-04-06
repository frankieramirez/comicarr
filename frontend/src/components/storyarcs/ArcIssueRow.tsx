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

interface ArcIssueRowProps {
  issue: GeneratedIssue;
}

const STATUS_CONFIG = {
  owned: {
    label: "Owned",
    dotClass: "bg-green-500",
    textClass: "text-green-700 dark:text-green-400",
  },
  wanted: {
    label: "Wanted",
    dotClass: "bg-yellow-500",
    textClass: "text-yellow-700 dark:text-yellow-400",
  },
  not_tracked: {
    label: "Not Tracked",
    dotClass: "bg-gray-400",
    textClass: "text-muted-foreground",
  },
} as const;

export default function ArcIssueRow({ issue }: ArcIssueRowProps) {
  const status =
    STATUS_CONFIG[issue.library_status] || STATUS_CONFIG.not_tracked;

  return (
    <div className="flex items-center gap-3 px-3 py-2 text-sm">
      <span className="w-6 text-right text-muted-foreground font-mono text-xs shrink-0">
        {issue.reading_order}
      </span>

      <div className="flex-1 min-w-0">
        <span className="font-medium text-foreground">{issue.series_name}</span>
        <span className="text-muted-foreground ml-1">
          #{issue.issue_number}
        </span>
        {issue.title && (
          <span className="text-muted-foreground ml-1.5 truncate">
            — {issue.title}
          </span>
        )}
      </div>

      <div className="flex items-center gap-1.5 shrink-0">
        <span className={`w-2 h-2 rounded-full ${status.dotClass}`} />
        <span className={`text-xs ${status.textClass}`}>{status.label}</span>
      </div>
    </div>
  );
}
