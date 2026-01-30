import { Download, X } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface BulkActionBarProps {
  selectedCount: number;
  onMarkWanted?: () => void;
  onSkip: () => void;
  onClear: () => void;
  isLoading?: boolean;
}

export default function BulkActionBar({ selectedCount, onMarkWanted, onSkip, onClear, isLoading }: BulkActionBarProps) {
  if (selectedCount === 0) return null;

  return (
    <div className="fixed bottom-0 left-0 right-0 bg-gradient-to-r from-blue-600 to-blue-700 text-white shadow-lg z-50">
      <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
        <div className="text-sm font-medium">
          {selectedCount} issue{selectedCount !== 1 ? 's' : ''} selected
        </div>
        <div className="flex items-center space-x-2">
          {onMarkWanted && (
            <Button
              variant="ghost"
              onClick={onMarkWanted}
              disabled={isLoading}
              className="text-white hover:bg-white/20"
            >
              <Download className="w-4 h-4 mr-2" />
              Mark Wanted
            </Button>
          )}
          <Button
            variant="ghost"
            onClick={onSkip}
            disabled={isLoading}
            className="text-white hover:bg-white/20"
          >
            <X className="w-4 h-4 mr-2" />
            Skip
          </Button>
          <Button
            variant="ghost"
            onClick={onClear}
            className="text-white hover:bg-white/20"
          >
            Clear Selection
          </Button>
        </div>
      </div>
    </div>
  );
}
