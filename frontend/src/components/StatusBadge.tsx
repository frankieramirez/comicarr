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
  dotColor: string;
  glowColor: string;
}

interface StatusBadgeProps {
  status?: string | null;
  showIcon?: boolean;
}

/**
 * StatusBadge component with luminous dot indicators
 */
export default function StatusBadge({
  status,
  showIcon = true,
}: StatusBadgeProps) {
  if (!status) return null;

  const normalizedStatus = status.toLowerCase();

  const statusMap: Record<string, StatusConfig> = {
    active: {
      variant: "active",
      label: "Active",
      dotColor: "var(--status-active)",
      glowColor: "var(--status-active)",
    },
    paused: {
      variant: "paused",
      label: "Paused",
      dotColor: "var(--status-paused)",
      glowColor: "var(--status-paused)",
    },
    ended: {
      variant: "ended",
      label: "Ended",
      dotColor: "var(--status-ended)",
      glowColor: "var(--status-ended)",
    },
    loading: {
      variant: "default",
      label: "Loading",
      dotColor: "var(--muted-foreground)",
      glowColor: "var(--muted-foreground)",
    },
    downloaded: {
      variant: "downloaded",
      label: "Downloaded",
      dotColor: "var(--status-downloaded)",
      glowColor: "var(--status-downloaded)",
    },
    wanted: {
      variant: "wanted",
      label: "Wanted",
      dotColor: "var(--status-wanted)",
      glowColor: "var(--status-wanted)",
    },
    skipped: {
      variant: "skipped",
      label: "Skipped",
      dotColor: "var(--status-skipped)",
      glowColor: "var(--status-skipped)",
    },
    snatched: {
      variant: "active",
      label: "Snatched",
      dotColor: "var(--status-active)",
      glowColor: "var(--status-active)",
    },
    archived: {
      variant: "default",
      label: "Archived",
      dotColor: "var(--muted-foreground)",
      glowColor: "var(--muted-foreground)",
    },
  };

  const config = statusMap[normalizedStatus] || {
    variant: "default" as BadgeVariant,
    label: status,
    dotColor: "var(--muted-foreground)",
    glowColor: "var(--muted-foreground)",
  };

  return (
    <Badge
      variant={config.variant}
      className="gap-1.5 rounded-full px-2.5 py-1"
    >
      {showIcon && (
        <span
          className="inline-block w-1.5 h-1.5 rounded-full"
          style={{
            backgroundColor: config.dotColor,
            boxShadow: `0 0 8px 2px color-mix(in srgb, ${config.glowColor} 50%, transparent)`,
          }}
        />
      )}
      {config.label}
    </Badge>
  );
}
