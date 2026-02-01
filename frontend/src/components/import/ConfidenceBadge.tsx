import { Badge } from "@/components/ui/badge";

interface ConfidenceBadgeProps {
  confidence: number | null;
  showLabel?: boolean;
}

export default function ConfidenceBadge({
  confidence,
  showLabel = true,
}: ConfidenceBadgeProps) {
  if (confidence === null || confidence === undefined) {
    return (
      <Badge variant="secondary" className="text-xs">
        {showLabel ? "Unknown" : "?"}
      </Badge>
    );
  }

  let variant: "default" | "secondary" | "destructive" | "outline" = "default";
  let colorClass = "";

  if (confidence >= 80) {
    colorClass = "bg-green-500/20 text-green-700 dark:text-green-400 border-green-500/30";
  } else if (confidence >= 50) {
    colorClass = "bg-yellow-500/20 text-yellow-700 dark:text-yellow-400 border-yellow-500/30";
  } else {
    colorClass = "bg-red-500/20 text-red-700 dark:text-red-400 border-red-500/30";
  }

  return (
    <Badge variant={variant} className={`text-xs ${colorClass}`}>
      {showLabel ? `${confidence}%` : confidence}
    </Badge>
  );
}
