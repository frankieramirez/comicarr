import { useEffect, useState, SubmitEvent } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import Logo from "@/components/Logo";
import type { LucideIcon } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { useTheme } from "@/contexts/ThemeContext";
import { isEditableTarget } from "@/lib/keyboard";
import { useAiStatus } from "@/hooks/useAiStatus";
import { useActivityStatus } from "@/hooks/useActivityStatus";
import VersionChip from "@/components/layout/VersionChip";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarInput,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  useSidebar,
} from "@/components/ui/sidebar";
import { Kbd } from "@/components/ui/kbd";
import { useToast } from "@/components/ui/toast";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  LayoutDashboard,
  BookOpen,
  Compass,
  Search,
  Calendar,
  ListTodo,
  Activity,
  Settings,
  LogOut,
  Monitor,
  Moon,
  Sun,
  FolderInput,
  ChevronsUpDown,
  ArrowUpRight,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { SEGMENTED_GROUP, SEGMENTED_ITEM } from "@/lib/segmented";
import type { ThemePreference } from "@/contexts/ThemeContext";

const THEME_OPTIONS: {
  value: ThemePreference;
  label: string;
  icon: LucideIcon;
}[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

interface NavItem {
  path: string;
  label: string;
  icon: LucideIcon;
  kbd?: string;
  /** Needs-you count; shown in error text, never as a filled badge. */
  count?: number;
}

export default function AppSidebar() {
  const { logout, user } = useAuth();
  const { preference, setPreference } = useTheme();
  const { addToast } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const { isMobile, setOpenMobile, state: sidebarState } = useSidebar();
  const [searchQuery, setSearchQuery] = useState("");
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const { data: aiStatus } = useAiStatus();
  const aiConfigured = aiStatus?.configured === true;
  const { data: activityStatus } = useActivityStatus();
  const attention = activityStatus?.attention ?? 0;

  const handleLogout = async () => {
    if (isLoggingOut) return;

    setIsLoggingOut(true);
    try {
      const result = await logout();
      if (result.success) {
        navigate("/login");
        return;
      }
      addToast({
        type: "error",
        message:
          "Logout failed. Your session is still active; please try again.",
      });
    } finally {
      setIsLoggingOut(false);
    }
  };

  const handleSearchSubmit = (e: SubmitEvent<HTMLFormElement>) => {
    e.preventDefault();
    const trimmed = searchQuery.trim();
    if (trimmed.length >= 3) {
      navigate(`/search?q=${encodeURIComponent(trimmed)}&page=1`);
      setSearchQuery("");
      setOpenMobile(false);
    }
  };

  // v2 nav: Story arcs lives inside Library; built-in AI (Discover, Ask
  // Comicarr) only appears once an AI provider is configured.
  const primaryNav: NavItem[] = [
    { path: "/", label: "Dashboard", icon: LayoutDashboard, kbd: "G D" },
    { path: "/library", label: "Library", icon: BookOpen, kbd: "G L" },
    { path: "/wanted", label: "Wanted", icon: ListTodo, kbd: "G W" },
    { path: "/releases", label: "Releases", icon: Calendar, kbd: "G R" },
    ...(aiConfigured
      ? [
          {
            path: "/discover",
            label: "Discover",
            icon: Compass,
            kbd: "G V",
          },
        ]
      : []),
  ];

  const managementNav: NavItem[] = [
    {
      path: "/activity",
      label: "Activity",
      icon: Activity,
      kbd: "G Y",
      count: attention,
    },
    { path: "/import", label: "Import", icon: FolderInput, kbd: "G I" },
    { path: "/settings", label: "Settings", icon: Settings, kbd: "G S" },
  ];

  const isActive = (path: string): boolean => {
    if (path === "/") {
      return location.pathname === "/";
    }
    // Story arcs are a tab of the Library page.
    if (path === "/library" && location.pathname.startsWith("/story-arcs")) {
      return true;
    }
    return location.pathname.startsWith(path);
  };

  const handleNavClick = () => {
    setOpenMobile(false);
  };

  const openChat = () => {
    setOpenMobile(false);
    navigate("/chat");
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (
        (event.metaKey || event.ctrlKey) &&
        event.shiftKey &&
        event.key.toLowerCase() === "k" &&
        !isEditableTarget(event.target) &&
        aiConfigured
      ) {
        event.preventDefault();
        setOpenMobile(false);
        navigate("/chat");
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [navigate, setOpenMobile, aiConfigured]);

  const username = user?.username || "admin";
  const avatarInitials = username.slice(0, 2).toUpperCase();

  const renderNav = (items: NavItem[]) =>
    items.map(({ path, label, icon: Icon, kbd, count }) => {
      const active = isActive(path);
      return (
        <SidebarMenuItem key={path}>
          <SidebarMenuButton asChild isActive={active} tooltip={label}>
            <Link to={path} onClick={handleNavClick}>
              <Icon className="w-4 h-4" />
              <span className="flex-1 text-[13px]">{label}</span>
              {count ? (
                <span
                  className="font-mono text-xs text-[var(--status-error)] group-data-[collapsible=icon]:hidden"
                  aria-label={`${count} need you`}
                >
                  {count}
                </span>
              ) : null}
              {!count && kbd && (
                <Kbd className="opacity-0 transition-opacity group-hover/menu-item:opacity-100 group-data-[collapsible=icon]:hidden font-mono text-[10px] tracking-wide">
                  {kbd}
                </Kbd>
              )}
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      );
    });

  return (
    <Sidebar collapsible="icon" variant="sidebar">
      {/* Brand header */}
      <SidebarHeader className="h-14 justify-center px-4 py-0">
        <div className="flex items-center gap-2">
          <Link
            to="/"
            onClick={handleNavClick}
            aria-label="Comicarr home"
            className="flex items-center gap-2 flex-1 min-w-0"
          >
            <Logo className="h-3.5 w-auto text-foreground" />
          </Link>
          <VersionChip />
        </div>
      </SidebarHeader>

      {/* Search with ⌘K hint */}
      <div className="px-2.5 pb-2">
        <form
          onSubmit={handleSearchSubmit}
          className="group-data-[collapsible=icon]:hidden"
        >
          <div className="relative flex h-8 items-center gap-2 rounded-md border border-border-strong bg-surface-2 px-2.5 transition-colors focus-within:border-border-emphasis focus-within:ring-2 focus-within:ring-ring/40">
            <Search className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
            <SidebarInput
              data-global-search="true"
              aria-label="Search"
              placeholder="Search or add"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-auto border-0 bg-transparent p-0 text-[13px] placeholder:text-foreground-2 focus-visible:ring-0 shadow-none"
            />
            <Kbd className="border-0 bg-transparent font-mono text-[10px]">
              ⌘K
            </Kbd>
          </div>
        </form>

        <div className="hidden group-data-[collapsible=icon]:flex justify-center">
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={() => navigate("/search")}
                aria-label="Search"
                className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
              >
                <Search className="w-4 h-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="right">Search</TooltipContent>
          </Tooltip>
        </div>
      </div>

      {/* Sections */}
      <SidebarContent className="px-2.5 pt-1">
        <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground px-2.5 pt-3 pb-1.5 group-data-[collapsible=icon]:hidden">
          Library
        </div>
        <SidebarMenu>{renderNav(primaryNav)}</SidebarMenu>

        <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground px-2.5 pt-5 pb-1.5 group-data-[collapsible=icon]:hidden">
          System
        </div>
        <SidebarMenu>{renderNav(managementNav)}</SidebarMenu>
      </SidebarContent>

      {/* Footer account menu keeps secondary actions out of the main navigation. */}
      <SidebarFooter className="px-2 pb-2 gap-0 border-t-[0.5px]">
        {/* Pinned launcher: Chat replaces the shell instead of navigating inside it.
            Only shown when an AI provider is configured (v2: MCP is the agent path). */}
        <div
          className={
            aiConfigured
              ? "py-2 group-data-[collapsible=icon]:hidden"
              : "hidden"
          }
        >
          <button
            type="button"
            onClick={openChat}
            className="flex h-9 w-full items-center gap-2.5 rounded-lg border border-sidebar-border bg-sidebar-accent/40 px-2.5 transition-colors hover:border-[color-mix(in_oklab,var(--primary)_50%,transparent)] hover:bg-sidebar-accent"
          >
            <span className="flex size-4.5 shrink-0 items-center justify-center rounded-control bg-primary/15">
              <span className="size-[5px] rounded-[1px] bg-primary" />
            </span>
            <span className="flex-1 text-left text-[13px] font-medium">
              Ask Comicarr
            </span>
            <ArrowUpRight className="w-3.5 h-3.5 text-muted-foreground" />
          </button>
          <div className="flex items-center justify-between gap-2 px-2.5 pt-1.5">
            <span className="mono-meta text-[10px]">
              ask about your library
            </span>
            <Kbd className="font-mono text-[10px]">⌘⇧K</Kbd>
          </div>
        </div>

        <div
          className={
            aiConfigured
              ? "hidden justify-center py-2 group-data-[collapsible=icon]:flex"
              : "hidden"
          }
        >
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={openChat}
                aria-label="Ask Comicarr"
                className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
              >
                <span className="flex size-4.5 items-center justify-center rounded-control bg-primary/15">
                  <span className="size-[5px] rounded-[1px] bg-primary" />
                </span>
              </button>
            </TooltipTrigger>
            <TooltipContent side="right">Ask Comicarr</TooltipContent>
          </Tooltip>
        </div>

        <SidebarMenu className="border-t-[0.5px] border-sidebar-border pt-1">
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <SidebarMenuButton
                    size="lg"
                    tooltip={username}
                    className="data-popup-open:bg-sidebar-accent data-popup-open:text-sidebar-accent-foreground"
                  />
                }
              >
                <Avatar className="size-8">
                  <AvatarFallback className="rounded-lg bg-surface-3 text-xs font-semibold text-foreground-2">
                    {avatarInitials}
                  </AvatarFallback>
                </Avatar>
                <span className="flex-1 truncate text-left text-sm font-medium">
                  {username}
                </span>
                <ChevronsUpDown className="ml-auto size-4" />
              </DropdownMenuTrigger>
              <DropdownMenuContent
                className={`rounded-lg ${!isMobile && sidebarState === "collapsed" ? "min-w-56" : "w-(--anchor-width)"}`}
                // Open upward over the trigger, at its width. Only the
                // collapsed icon rail has no room above, so it opens right.
                side={
                  !isMobile && sidebarState === "collapsed" ? "right" : "top"
                }
                align={
                  !isMobile && sidebarState === "collapsed" ? "end" : "start"
                }
                sideOffset={4}
              >
                <div className="flex items-center gap-2 px-2 py-1.5 text-[13px]">
                  <span className="text-foreground-2">Theme</span>
                  <div
                    role="group"
                    aria-label="Theme"
                    className={`ml-auto ${SEGMENTED_GROUP}`}
                  >
                    {THEME_OPTIONS.map(({ value, label, icon: Icon }) => (
                      <button
                        key={value}
                        type="button"
                        aria-pressed={preference === value}
                        aria-label={label}
                        title={label}
                        onClick={() => setPreference(value)}
                        className={`${SEGMENTED_ITEM} h-6 px-2 [&>svg]:size-3.5`}
                      >
                        <Icon aria-hidden="true" />
                      </button>
                    ))}
                  </div>
                </div>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                  <DropdownMenuItem
                    onClick={() => {
                      navigate("/settings");
                      handleNavClick();
                    }}
                  >
                    <Settings />
                    Settings
                    <DropdownMenuShortcut className="font-mono tracking-normal">
                      G S
                    </DropdownMenuShortcut>
                  </DropdownMenuItem>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  disabled={isLoggingOut}
                  onClick={handleLogout}
                >
                  <LogOut />
                  {isLoggingOut ? "Logging out…" : "Log out"}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
