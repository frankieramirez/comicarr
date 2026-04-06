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

interface ActivityFeedDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ActivityFeedDrawer({
  open,
  onOpenChange,
}: ActivityFeedDrawerProps) {
  const { data: entries, isLoading } = useAiActivity(50);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex flex-col p-0 sm:max-w-md">
        <SheetHeader className="px-4 pt-6 pb-4 border-b border-border">
          <SheetTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5" />
            AI Activity
          </SheetTitle>
          <SheetDescription>Recent AI processing activity</SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto">
          {isLoading && (
            <div className="flex items-center justify-center py-12">
              <p className="text-sm text-muted-foreground">
                Loading activity...
              </p>
            </div>
          )}

          {!isLoading && (!entries || entries.length === 0) && (
            <div className="flex flex-col items-center justify-center py-12 px-4">
              <Activity className="h-8 w-8 text-muted-foreground mb-3" />
              <p className="text-sm text-muted-foreground text-center">
                No AI activity yet
              </p>
              <p className="text-xs text-muted-foreground text-center mt-1">
                Activity will appear here when AI features are used
              </p>
            </div>
          )}

          {!isLoading &&
            entries &&
            entries.length > 0 &&
            entries.map((entry) => (
              <ActivityFeedEntry key={entry.id} entry={entry} />
            ))}
        </div>
      </SheetContent>
    </Sheet>
  );
}
