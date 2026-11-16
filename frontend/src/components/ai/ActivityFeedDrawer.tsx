import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useDirection } from "@/hooks/useDirection";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { useAiActivity } from "@/hooks/useAiActivity";
import { ActivityFeedEntry } from "./ActivityFeedEntry";
import { Activity } from "lucide-react";
import { PanelUnavailable } from "@/components/dashboard/DashboardPanel";
import { panelState } from "@/lib/panelState";

interface ActivityFeedDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ActivityFeedDrawer({
  open,
  onOpenChange,
}: ActivityFeedDrawerProps) {
  const direction = useDirection();
  const query = useAiActivity(50, { enabled: open });
  const entries = query.data ?? [];
  const state = panelState(query, entries.length === 0);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side={direction === "rtl" ? "left" : "right"}
        className="flex flex-col p-0 sm:max-w-md"
      >
        <SheetHeader className="px-4 pt-6 pb-4 border-b border-border">
          <SheetTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5" />
            <Trans>AI Activity</Trans>
          </SheetTitle>
          <SheetDescription>
            <Trans>Recent AI processing activity</Trans>
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto">
          {state === "loading" && (
            <div className="flex items-center justify-center py-12">
              <p className="text-sm text-muted-foreground">
                <Trans>Loading activity...</Trans>
              </p>
            </div>
          )}

          {state === "unavailable" && (
            <div className="px-4">
              <PanelUnavailable
                label={t`AI activity`}
                onRetry={() => void query.refetch()}
                isRetrying={query.isFetching}
              />
            </div>
          )}

          {state === "empty" && (
            <div className="flex flex-col items-center justify-center py-12 px-4">
              <Activity className="h-8 w-8 text-muted-foreground mb-3" />
              <p className="text-sm text-muted-foreground text-center">
                <Trans>No AI activity yet</Trans>
              </p>
              <p className="text-xs text-muted-foreground text-center mt-1">
                <Trans>
                  Activity will appear here when AI features are used
                </Trans>
              </p>
            </div>
          )}

          {state === "content" &&
            entries.map((entry) => (
              <ActivityFeedEntry key={entry.id} entry={entry} />
            ))}
        </div>
      </SheetContent>
    </Sheet>
  );
}
