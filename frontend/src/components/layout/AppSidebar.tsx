import { useEffect, useMemo, useState, SubmitEvent } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import Logo from "@/components/Logo";
import type { LucideIcon } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { useTheme } from "@/contexts/ThemeContext";
import { useChatThreads } from "@/hooks/useLibraryChat";
import { isEditableTarget } from "@/lib/keyboard";
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
  Search,
  Calendar,
  ListTodo,
  BookMarked,
  Activity,
  Settings,
  LogOut,
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
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";

interface NavItem {
  path: string;
  label: string;
  icon: LucideIcon;
  kbd?: string;
}

export default function AppSidebar() {
  const { logout, user } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const { addToast } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const { isMobile, setOpenMobile } = useSidebar();
  const [searchQuery, setSearchQuery] = useState("");
  const [isLoggingOut, setIsLoggingOut] = useState(false);

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

  const primaryNav: NavItem[] = [
    { path: "/", label: "Dashboard", icon: LayoutDashboard, kbd: "G D" },
    { path: "/library", label: "Library", icon: BookOpen, kbd: "G L" },
    { path: "/releases", label: "Releases", icon: Calendar, kbd: "G R" },
    { path: "/wanted", label: "Wanted", icon: ListTodo, kbd: "G W" },
    { path: "/story-arcs", label: "Story Arcs", icon: BookMarked, kbd: "G A" },
  ];

  const managementNav: NavItem[] = [
    { path: "/activity", label: "Activity", icon: Activity, kbd: "G Y" },
    { path: "/import", label: "Import", icon: FolderInput, kbd: "G I" },
  ];

  const isActive = (path: string): boolean => {
    if (path === "/") {
      return location.pathname === "/";
    }
    return location.pathname.startsWith(path);
  };

  const handleNavClick = () => {
    setOpenMobile(false);
  };

  const chatThreadsQuery = useChatThreads();
  const chatsToday = useMemo(() => {
    const today = new Date().toDateString();
    return (
      chatThreadsQuery.data?.pages.flatMap((page) => page.threads) || []
    ).filter((thread) => new Date(thread.updated_at).toDateString() === today)
      .length;
  }, [chatThreadsQuery.data]);

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
        !isEditableTarget(event.target)
      ) {
        event.preventDefault();
        setOpenMobile(false);
        navigate("/chat");
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [navigate, setOpenMobile]);

  const username = user?.username || "admin";
  const avatarInitials = username.slice(0, 2).toUpperCase();

  const renderNav = (items: NavItem[]) =>
    items.map(({ path, label, icon: Icon, kbd }) => {
      const active = isActive(path);
      return (
        <SidebarMenuItem key={path}>
          <SidebarMenuButton asChild isActive={active} tooltip={label}>
            <Link to={path} onClick={handleNavClick}>
              <Icon className="w-4 h-4" />
              <span className="flex-1 text-[13px]">{label}</span>
              {active && kbd && (
                <Kbd className="group-data-[collapsible=icon]:hidden font-mono text-[10px] tracking-wide">
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
      <SidebarHeader className="px-3 pt-3 pb-3 border-b-[0.5px] border-sidebar-border h-12">
        <div className="flex items-center gap-2">
          <Link
            to="/"
            onClick={handleNavClick}
            className="flex items-center gap-2 flex-1 min-w-0"
          >
            <Logo className="h-3 w-auto text-foreground" />
          </Link>
          <VersionChip />
        </div>
      </SidebarHeader>

      {/* Search with ⌘K hint */}
      <div className="px-2 pt-2 pb-1">
        <form
          onSubmit={handleSearchSubmit}
          className="group-data-[collapsible=icon]:hidden"
        >
          <div className="relative flex items-center gap-2 px-2.5 py-1.5 rounded-md border border-sidebar-border bg-secondary/60 transition-colors focus-within:border-primary focus-within:bg-background focus-within:ring-2 focus-within:ring-[color-mix(in_oklab,var(--primary)_28%,transparent)]">
            <Search className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
            <SidebarInput
              data-global-search="true"
              placeholder="Search..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-auto border-0 bg-transparent p-0 text-[12px] placeholder:text-muted-foreground focus-visible:ring-0 shadow-none"
            />
            <Kbd className="font-mono text-[10px] bg-background border border-sidebar-border">
              ⌘K
            </Kbd>
          </div>
        </form>

        <div className="hidden group-data-[collapsible=icon]:flex justify-center">
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={() => navigate("/search")}
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
      <SidebarContent className="px-2 pt-1">
        <div className="mono-label px-2 pt-2 pb-1 group-data-[collapsible=icon]:hidden">
          Library
        </div>
        <SidebarMenu>{renderNav(primaryNav)}</SidebarMenu>

        <div className="mono-label px-2 pt-4 pb-1 group-data-[collapsible=icon]:hidden">
          System
        </div>
        <SidebarMenu>{renderNav(managementNav)}</SidebarMenu>
      </SidebarContent>

      {/* Footer account menu keeps secondary actions out of the main navigation. */}
      <SidebarFooter className="px-2 pb-2 gap-0 border-t-[0.5px]">
        {/* Pinned launcher: Chat replaces the shell instead of navigating inside it. */}
        <div className="py-2 group-data-[collapsible=icon]:hidden">
          <button
            type="button"
            onClick={openChat}
            className="flex h-9 w-full items-center gap-2.5 rounded-lg border border-sidebar-border bg-sidebar-accent/40 px-2.5 transition-colors hover:border-[color-mix(in_oklab,var(--primary)_50%,transparent)] hover:bg-sidebar-accent"
          >
            <span className="flex size-4.5 shrink-0 items-center justify-center rounded-[5px] bg-primary/15">
              <span className="size-[5px] rounded-[1px] bg-primary" />
            </span>
            <span className="flex-1 text-left text-[13px] font-medium">
              Ask Comicarr
            </span>
            <ArrowUpRight className="w-3.5 h-3.5 text-muted-foreground" />
          </button>
          <div className="flex items-center justify-between gap-2 px-2.5 pt-1.5">
            <span className="mono-meta text-[10px]">
              {chatsToday > 0
                ? `${chatsToday} chat${chatsToday === 1 ? "" : "s"} today`
                : "ask about your library"}
            </span>
            <Kbd className="font-mono text-[10px]">⌘⇧K</Kbd>
          </div>
        </div>

        <div className="hidden justify-center py-2 group-data-[collapsible=icon]:flex">
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={openChat}
                aria-label="Ask Comicarr"
                className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
              >
                <span className="flex size-4.5 items-center justify-center rounded-[5px] bg-primary/15">
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
                  <AvatarFallback className="rounded-lg bg-linear-to-br from-primary to-chart-4 text-xs font-semibold text-primary-foreground">
                    {avatarInitials}
                  </AvatarFallback>
                </Avatar>
                <span className="flex-1 truncate text-left text-sm font-medium">
                  {username}
                </span>
                <ChevronsUpDown className="ml-auto size-4" />
              </DropdownMenuTrigger>
              <DropdownMenuContent
                className="w-(--anchor-width) min-w-56 rounded-lg"
                side={isMobile ? "bottom" : "right"}
                align="end"
                sideOffset={4}
              >
                <DropdownMenuGroup>
                  <DropdownMenuLabel className="p-0 font-normal">
                    <div className="flex items-center gap-2 px-1 py-1.5 text-left text-sm">
                      <Avatar className="h-8 w-8 rounded-lg">
                        <AvatarFallback className="rounded-lg bg-linear-to-br from-primary to-chart-4 text-xs font-semibold text-primary-foreground">
                          {avatarInitials}
                        </AvatarFallback>
                      </Avatar>
                      <div className="grid flex-1 text-left text-sm leading-tight">
                        <span className="truncate font-medium">{username}</span>
                        <span className="truncate text-xs text-muted-foreground">
                          {theme === "light" ? "light" : "dark"} mode
                        </span>
                      </div>
                    </div>
                  </DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={() => {
                      navigate("/settings");
                      handleNavClick();
                    }}
                  >
                    <Settings />
                    Settings
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={toggleTheme}>
                    {theme === "light" ? <Moon /> : <Sun />}
                    {theme === "light" ? "Dark mode" : "Light mode"}
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
