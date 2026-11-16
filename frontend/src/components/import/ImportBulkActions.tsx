import { plural, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { EyeOff, Eye, Trash2, X } from "lucide-react";

interface ImportBulkActionsProps {
  selectedFileCount: number;
  selectedGroupCount: number;
  onIgnore: () => void;
  onUnignore: () => void;
  onDelete: () => void;
  onClear: () => void;
  isLoading?: boolean;
  showUnignore?: boolean;
}

export default function ImportBulkActions({
  selectedFileCount,
  selectedGroupCount,
  onIgnore,
  onUnignore,
  onDelete,
  onClear,
  isLoading = false,
  showUnignore = false,
}: ImportBulkActionsProps) {
  if (selectedFileCount === 0) return null;

  const groupCount = plural(selectedGroupCount, {
    one: "# group",
    other: "# groups",
  });
  const fileCount = plural(selectedFileCount, {
    one: "# file",
    other: "# files",
  });

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 animate-in slide-in-from-bottom-4 duration-200">
      <div className="bg-card border border-border rounded-lg shadow-lg px-4 py-3 flex items-center gap-4">
        <span className="text-sm font-medium text-foreground">
          {t`${groupCount} · ${fileCount} selected`}
        </span>

        <div className="h-4 w-px bg-border" />

        <TooltipProvider delayDuration={150}>
          <div className="flex items-center gap-2">
            {showUnignore ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={onUnignore}
                    disabled={isLoading}
                  >
                    <Eye className="w-4 h-4 me-1" />
                    <Trans>Unignore</Trans>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <Trans>Unignore selected import files</Trans>
                </TooltipContent>
              </Tooltip>
            ) : (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={onIgnore}
                    disabled={isLoading}
                  >
                    <EyeOff className="w-4 h-4 me-1" />
                    <Trans>Ignore</Trans>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <Trans>Ignore selected import files</Trans>
                </TooltipContent>
              </Tooltip>
            )}

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={onDelete}
                  disabled={isLoading}
                >
                  <Trash2 className="w-4 h-4 me-1" />
                  <Trans>Delete</Trans>
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <Trans>Delete selected import records</Trans>
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={onClear}
                  disabled={isLoading}
                  aria-label={t`Clear selected imports`}
                >
                  <X className="w-4 h-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <Trans>Clear selection</Trans>
              </TooltipContent>
            </Tooltip>
          </div>
        </TooltipProvider>
      </div>
    </div>
  );
}
