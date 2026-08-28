import { useState } from "react";
import { useLocation } from "react-router-dom";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import AppSidebar from "@/components/layout/AppSidebar";
import AppStatusBar from "@/components/layout/AppStatusBar";
import { useAiStatus } from "@/hooks/useAiStatus";
import { ActivityFeedDrawer } from "@/components/ai/ActivityFeedDrawer";
import WhatsNewModal from "@/components/whats-new/WhatsNewModal";
import { Bell } from "lucide-react";
import { isMockEnabled } from "@/lib/mockData";

const FULL_BLEED_ROUTES = [
  "/",
  "/library",
  "/settings",
  "/search",
  "/releases",
  "/wanted",
  "/story-arcs",
  "/activity",
  "/import",
];
const FULL_BLEED_PREFIXES = ["/library/", "/series/", "/story-arcs/"];

interface LayoutProps {
  children: React.ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  const { data: aiStatus } = useAiStatus();
  const [activityOpen, setActivityOpen] = useState(false);
  const { pathname } = useLocation();

  const showAiBell = aiStatus?.configured === true;
  const fullBleed =
    FULL_BLEED_ROUTES.includes(pathname) ||
    FULL_BLEED_PREFIXES.some((p) => pathname.startsWith(p));
  const mock = isMockEnabled();

  return (
    <SidebarProvider className="h-svh overflow-hidden">
      <AppSidebar />
      {/* No height of its own: as a flex item it stretches to the shell's
          height, so the column below is bounded by the viewport. */}
      <main className="flex min-h-0 min-w-0 flex-1 flex-col">
        {/* Mobile header with trigger - only visible on mobile */}
        <header className="z-10 flex h-16 shrink-0 items-center gap-4 border-b bg-background px-4 md:hidden">
          <SidebarTrigger />
          <span className="text-lg font-bold gradient-brand">Comicarr</span>
          {showAiBell && (
            <div className="ml-auto flex items-center gap-1">
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
        <div className="hidden md:flex h-12 shrink-0 items-center gap-3 border-b-[0.5px] border-border bg-card px-4 font-mono text-[11px] text-muted-foreground">
          <SidebarTrigger />
          <AppStatusBar />
          <div className="ml-auto flex items-center gap-3">
            {mock && (
              <span
                className="px-1.5 py-0.5 rounded-sm border font-mono text-[10px] tracking-wider uppercase"
                style={{
                  borderColor: "var(--primary)",
                  color: "var(--primary)",
                  background:
                    "color-mix(in oklab, var(--primary) 12%, transparent)",
                }}
                title="Mock data — disable with ?mock=0"
              >
                mock
              </span>
            )}
            {showAiBell && (
              <button
                onClick={() => setActivityOpen(true)}
                className="rounded-sm p-1 text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
                aria-label="AI Activity"
              >
                <Bell className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* Main content area. Full-bleed pages scroll internally so their
            footers can stay on the viewport edge; centred pages scroll here. */}
        <div
          className={`flex-1 min-h-0 min-w-0 ${fullBleed ? "overflow-hidden" : "overflow-auto"}`}
        >
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
      {/* Post-upgrade What's New — only when pending_whats_new is set (#474). */}
      <WhatsNewModal />
    </SidebarProvider>
  );
}
