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

  const variant: "default" | "secondary" | "destructive" | "outline" =
    "default";
  const colorClass =
    confidence >= 80
      ? "bg-green-500/20 text-green-700 dark:text-green-400 border-green-500/30"
      : confidence >= 50
        ? "bg-yellow-500/20 text-yellow-700 dark:text-yellow-400 border-yellow-500/30"
        : "bg-red-500/20 text-red-700 dark:text-red-400 border-red-500/30";

  return (
    <Badge variant={variant} className={`text-xs ${colorClass}`}>
      {showLabel ? `${confidence}%` : confidence}
    </Badge>
  );
}
