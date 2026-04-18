import { useState } from "react";
import { useLocation } from "react-router-dom";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import AppSidebar from "@/components/layout/AppSidebar";
import { useAiStatus } from "@/hooks/useAiStatus";
import { ActivityFeedDrawer } from "@/components/ai/ActivityFeedDrawer";
import { ChatPanel } from "@/components/ai/ChatPanel";
import { Bell, MessageCircle } from "lucide-react";

const FULL_BLEED_ROUTES = ["/", "/library"];

interface LayoutProps {
  children: React.ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  const { data: aiStatus } = useAiStatus();
  const [activityOpen, setActivityOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const { pathname } = useLocation();

  const showAiBell = aiStatus?.configured === true;
  const fullBleed = FULL_BLEED_ROUTES.includes(pathname);

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

        {/* Desktop omni status bar */}
        <div className="hidden md:flex h-9 items-center gap-3 border-b border-border bg-card px-4 font-mono text-[11px] text-muted-foreground">
          <span className="text-foreground uppercase tracking-wide">
            Comicarr
          </span>
          <span className="text-[var(--text-muted)]">/</span>
          <span>
            mode: <span className="text-foreground">production</span>
          </span>
          <span className="text-[var(--text-muted)]">·</span>
          <span>
            db: <span style={{ color: "var(--status-active)" }}>healthy</span>
          </span>
          <span className="text-[var(--text-muted)]">·</span>
          <span>
            queue: <span className="text-foreground">—</span>
          </span>
          <div className="ml-auto flex items-center gap-3">
            {showAiBell && (
              <>
                <button
                  onClick={() => setChatOpen(true)}
                  className="rounded-sm p-1 text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
                  aria-label="AI Chat"
                >
                  <MessageCircle className="h-3.5 w-3.5" />
                </button>
                <button
                  onClick={() => setActivityOpen(true)}
                  className="rounded-sm p-1 text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
                  aria-label="AI Activity"
                >
                  <Bell className="h-3.5 w-3.5" />
                </button>
              </>
            )}
          </div>
        </div>

        {/* Main content area */}
        <div className="flex-1 overflow-auto min-w-0">
          {fullBleed ? (
            children
          ) : (
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
              {children}
            </div>
          )}
        </div>
      </main>

      <ActivityFeedDrawer open={activityOpen} onOpenChange={setActivityOpen} />
      <ChatPanel open={chatOpen} onOpenChange={setChatOpen} />
    </SidebarProvider>
  );
}
