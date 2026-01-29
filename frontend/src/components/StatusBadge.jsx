import { Badge } from '@/components/ui/badge';

/**
 * StatusBadge component to display series or issue status
 */
export default function StatusBadge({ status }) {
  if (!status) return null;

  const normalizedStatus = status.toLowerCase();

  // Map status to badge variants
  const statusMap = {
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

  const config = statusMap[normalizedStatus] || { variant: 'default', label: status };

  return <Badge variant={config.variant}>{config.label}</Badge>;
}
