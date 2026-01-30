import {
  Check,
  Clock,
  MinusCircle,
  Play,
  Pause,
  CircleDot,
  Download,
  Archive,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";

type BadgeVariant =
  | "default"
  | "active"
  | "paused"
  | "ended"
  | "wanted"
  | "downloaded"
  | "skipped";

interface StatusConfig {
  variant: BadgeVariant;
  label: string;
  icon?: React.ReactNode;
}

interface StatusBadgeProps {
  status?: string | null;
  showIcon?: boolean;
}

/**
 * StatusBadge component to display series or issue status with optional icons
 */
export default function StatusBadge({
  status,
  showIcon = true,
}: StatusBadgeProps) {
  if (!status) return null;

  const normalizedStatus = status.toLowerCase();

  // Map status to badge variants with icons
  const statusMap: Record<string, StatusConfig> = {
    active: {
      variant: "active",
      label: "Active",
      icon: <Play className="w-3 h-3" />,
    },
    paused: {
      variant: "paused",
      label: "Paused",
      icon: <Pause className="w-3 h-3" />,
    },
    ended: {
      variant: "ended",
      label: "Ended",
      icon: <CircleDot className="w-3 h-3" />,
    },
    loading: {
      variant: "default",
      label: "Loading",
      icon: <Clock className="w-3 h-3" />,
    },

    // Issue statuses
    downloaded: {
      variant: "downloaded",
      label: "Downloaded",
      icon: <Check className="w-3 h-3" />,
    },
    wanted: {
      variant: "wanted",
      label: "Wanted",
      icon: <Download className="w-3 h-3" />,
    },
    skipped: {
      variant: "skipped",
      label: "Skipped",
      icon: <MinusCircle className="w-3 h-3" />,
    },
    snatched: {
      variant: "active",
      label: "Snatched",
      icon: <Download className="w-3 h-3" />,
    },
    archived: {
      variant: "default",
      label: "Archived",
      icon: <Archive className="w-3 h-3" />,
    },
  };

  const config = statusMap[normalizedStatus] || {
    variant: "default" as BadgeVariant,
    label: status,
    icon: null,
  };

  return (
    <Badge variant={config.variant} className="gap-1">
      {showIcon && config.icon}
      {config.label}
    </Badge>
  );
}
