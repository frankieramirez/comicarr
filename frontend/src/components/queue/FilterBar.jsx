import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';

export default function FilterBar({ showAll, onToggleFilter, onRefresh, isRefreshing }) {
  return (
    <div className="flex items-center justify-between mb-4">
      <div className="flex items-center space-x-2">
        <Button
          variant={showAll ? "outline" : "default"}
          onClick={() => onToggleFilter(false)}
        >
          New Only
        </Button>
        <Button
          variant={showAll ? "default" : "outline"}
          onClick={() => onToggleFilter(true)}
        >
          All Releases
        </Button>
      </div>
      <Button variant="outline" onClick={onRefresh} disabled={isRefreshing}>
        <RefreshCw className={`w-4 h-4 mr-2 ${isRefreshing ? 'animate-spin' : ''}`} />
        Refresh
      </Button>
    </div>
  );
}
