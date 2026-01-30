import { Badge } from '@/components/ui/badge';

type BadgeVariant = 'default' | 'active' | 'paused' | 'ended' | 'wanted' | 'downloaded' | 'skipped';

interface StatusConfig {
  variant: BadgeVariant;
  label: string;
}

interface StatusBadgeProps {
  status?: string | null;
}

/**
 * StatusBadge component to display series or issue status
 */
export default function StatusBadge({ status }: StatusBadgeProps) {
  if (!status) return null;

  const normalizedStatus = status.toLowerCase();

  // Map status to badge variants
  const statusMap: Record<string, StatusConfig> = {
    active: { variant: 'active', label: 'Active' },
    paused: { variant: 'paused', label: 'Paused' },
    ended: { variant: 'ended', label: 'Ended' },
    loading: { variant: 'default', label: 'Loading' },

    // Issue statuses
    downloaded: { variant: 'downloaded', label: 'Downloaded' },
    wanted: { variant: 'wanted', label: 'Wanted' },
    skipped: { variant: 'skipped', label: 'Skipped' },
    snatched: { variant: 'active', label: 'Snatched' },
    archived: { variant: 'default', label: 'Archived' },
  };

  const config = statusMap[normalizedStatus] || { variant: 'default' as BadgeVariant, label: status };

  return <Badge variant={config.variant}>{config.label}</Badge>;
}
