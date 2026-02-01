import { Button } from "@/components/ui/button";
import { EyeOff, Eye, Trash2, X } from "lucide-react";

interface ImportBulkActionsProps {
  selectedCount: number;
  onIgnore: () => void;
  onUnignore: () => void;
  onDelete: () => void;
  onClear: () => void;
  isLoading?: boolean;
  showUnignore?: boolean;
}

export default function ImportBulkActions({
  selectedCount,
  onIgnore,
  onUnignore,
  onDelete,
  onClear,
  isLoading = false,
  showUnignore = false,
}: ImportBulkActionsProps) {
  if (selectedCount === 0) return null;

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 animate-in slide-in-from-bottom-4 duration-200">
      <div className="bg-card border border-card-border rounded-lg shadow-lg px-4 py-3 flex items-center gap-4">
        <span className="text-sm font-medium text-foreground">
          {selectedCount} selected
        </span>

        <div className="h-4 w-px bg-border" />

        <div className="flex items-center gap-2">
          {showUnignore ? (
            <Button
              size="sm"
              variant="outline"
              onClick={onUnignore}
              disabled={isLoading}
            >
              <Eye className="w-4 h-4 mr-1" />
              Unignore
            </Button>
          ) : (
            <Button
              size="sm"
              variant="outline"
              onClick={onIgnore}
              disabled={isLoading}
            >
              <EyeOff className="w-4 h-4 mr-1" />
              Ignore
            </Button>
          )}

          <Button
            size="sm"
            variant="destructive"
            onClick={onDelete}
            disabled={isLoading}
          >
            <Trash2 className="w-4 h-4 mr-1" />
            Delete
          </Button>

          <Button
            size="sm"
            variant="ghost"
            onClick={onClear}
            disabled={isLoading}
          >
            <X className="w-4 h-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
