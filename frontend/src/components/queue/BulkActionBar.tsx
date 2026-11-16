import { plural } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Download, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";

interface BulkActionBarProps {
  selectedCount: number;
  onMarkWanted?: () => void;
  onSearch?: () => void;
  onSkip: () => void;
  onClear: () => void;
  isLoading?: boolean;
}

export default function BulkActionBar({
  selectedCount,
  onMarkWanted,
  onSearch,
  onSkip,
  onClear,
  isLoading,
}: BulkActionBarProps) {
  if (selectedCount === 0) return null;

  return (
    <div className="fixed bottom-0 left-0 right-0 border-t border-border bg-popover text-popover-foreground shadow-lg z-50">
      <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
        <div className="text-sm font-medium">
          {plural(selectedCount, {
            one: "# issue selected",
            other: "# issues selected",
          })}
        </div>
        <div className="flex items-center space-x-2">
          {onMarkWanted && (
            <Button
              variant="ghost"
              onClick={onMarkWanted}
              disabled={isLoading}
              className="text-foreground hover:bg-accent"
            >
              <Download className="w-4 h-4 mr-2" />
              <Trans>Mark Wanted</Trans>
            </Button>
          )}
          {onSearch && selectedCount === 1 && (
            <Button
              variant="ghost"
              onClick={onSearch}
              disabled={isLoading}
              className="text-foreground hover:bg-accent"
            >
              <Search className="w-4 h-4 mr-2" />
              <Trans>Search selected</Trans>
            </Button>
          )}
          <Button
            variant="ghost"
            onClick={onSkip}
            disabled={isLoading}
            className="text-foreground hover:bg-accent"
          >
            <X className="w-4 h-4 mr-2" />
            <Trans>Skip</Trans>
          </Button>
          <Button
            variant="ghost"
            onClick={onClear}
            className="text-foreground hover:bg-accent"
          >
            <Trans>Clear Selection</Trans>
          </Button>
        </div>
      </div>
    </div>
  );
}
