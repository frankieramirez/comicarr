import { useState } from "react";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import AppSidebar from "@/components/layout/AppSidebar";
import { useAiStatus } from "@/hooks/useAiStatus";
import { ActivityFeedDrawer } from "@/components/ai/ActivityFeedDrawer";
import { ChatPanel } from "@/components/ai/ChatPanel";
import { Bell, MessageCircle } from "lucide-react";

interface LayoutProps {
  children: React.ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  const { data: aiStatus } = useAiStatus();
  const [activityOpen, setActivityOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);

  const showAiBell = aiStatus?.configured === true;

  return (
    <SidebarProvider>
      <AppSidebar />
      <main className="flex-1 min-w-0">
        {/* Mobile header with trigger - only visible on mobile */}
        <header className="sticky top-0 z-10 flex h-16 items-center gap-4 border-b bg-background px-4 md:hidden">
          <SidebarTrigger />
          <span className="text-lg font-bold gradient-brand">Comicarr</span>
          {showAiBell && (
            <div className="ml-auto flex items-center gap-1">
              <button
                onClick={() => setChatOpen(true)}
                className="rounded-md p-2 text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                aria-label="AI Chat"
              >
                <MessageCircle className="h-5 w-5" />
              </button>
              <button
                onClick={() => setActivityOpen(true)}
                className="rounded-md p-2 text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                aria-label="AI Activity"
              >
                <Bell className="h-5 w-5" />
              </button>
            </div>
          )}
        </header>

        {/* Main content area */}
        <div className="flex-1 overflow-auto min-w-0">
          {/* Desktop AI buttons */}
          {showAiBell && (
            <div className="hidden md:flex justify-end gap-1 px-4 sm:px-6 lg:px-8 pt-4 max-w-7xl mx-auto">
              <button
                onClick={() => setChatOpen(true)}
                className="rounded-md p-2 text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                aria-label="AI Chat"
              >
                <MessageCircle className="h-5 w-5" />
              </button>
              <button
                onClick={() => setActivityOpen(true)}
                className="rounded-md p-2 text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                aria-label="AI Activity"
              >
                <Bell className="h-5 w-5" />
              </button>
            </div>
          )}
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
            {children}
          </div>
        </div>
      </main>

      <ActivityFeedDrawer open={activityOpen} onOpenChange={setActivityOpen} />
      <ChatPanel open={chatOpen} onOpenChange={setChatOpen} />
    </SidebarProvider>
  );
}
