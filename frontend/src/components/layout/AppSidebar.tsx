import { useState, FormEvent } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import Logo from "@/components/Logo";
import type { LucideIcon } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { useTheme } from "@/contexts/ThemeContext";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarInput,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarSeparator,
  useSidebar,
} from "@/components/ui/sidebar";
import { Kbd } from "@/components/ui/kbd";
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
} from "lucide-react";

interface NavItem {
  path: string;
  label: string;
  icon: LucideIcon;
  kbd?: string;
}

export default function AppSidebar() {
  const { logout, user } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const { setOpenMobile } = useSidebar();
  const [searchQuery, setSearchQuery] = useState("");

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const handleSearchSubmit = (e: FormEvent<HTMLFormElement>) => {
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

  const username =
    typeof user === "object" && user && "username" in user
      ? (user as { username?: string }).username || "admin"
      : "admin";

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
      <SidebarHeader className="px-3 pt-3 pb-3 border-b border-sidebar-border">
        <div className="flex items-center gap-2">
          <Link
            to="/"
            onClick={handleNavClick}
            className="flex items-center gap-2 flex-1 min-w-0"
          >
            <Logo className="h-4 w-auto text-foreground" />
          </Link>
          <span className="group-data-[collapsible=icon]:hidden font-mono text-[10px] text-[var(--text-muted)] px-1.5 py-0.5 border border-sidebar-border rounded-sm">
            0.15
          </span>
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

      <SidebarSeparator />

      {/* Footer: settings, theme, logout + account */}
      <SidebarFooter className="px-2 pb-2 gap-0">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              asChild
              isActive={isActive("/settings")}
              tooltip="Settings"
            >
              <Link to="/settings" onClick={handleNavClick}>
                <Settings className="w-4 h-4" />
                <span className="flex-1 text-[13px]">Settings</span>
                {isActive("/settings") && (
                  <Kbd className="group-data-[collapsible=icon]:hidden font-mono text-[10px]">
                    ⌘,
                  </Kbd>
                )}
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>

          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={toggleTheme}
              tooltip={theme === "light" ? "Dark mode" : "Light mode"}
            >
              {theme === "light" ? (
                <Moon className="w-4 h-4" />
              ) : (
                <Sun className="w-4 h-4" />
              )}
              <span className="flex-1 text-[13px]">
                {theme === "light" ? "Dark mode" : "Light mode"}
              </span>
            </SidebarMenuButton>
          </SidebarMenuItem>

          <SidebarMenuItem>
            <SidebarMenuButton onClick={handleLogout} tooltip="Logout">
              <LogOut className="w-4 h-4" />
              <span className="flex-1 text-[13px]">Logout</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>

        {/* Account footer with status dot */}
        <div className="mt-2 pt-2 border-t border-sidebar-border flex items-center gap-2 px-2 py-1.5 group-data-[collapsible=icon]:hidden">
          <div
            className="w-6 h-6 rounded-full shrink-0"
            style={{
              background:
                "linear-gradient(135deg, var(--primary), var(--chart-4))",
            }}
          />
          <div className="flex-1 min-w-0">
            <div className="text-[12px] font-medium truncate">{username}</div>
            <div className="font-mono text-[10px] text-[var(--text-muted)]">
              admin · ready
            </div>
          </div>
          <div
            className="w-1.5 h-1.5 rounded-full"
            style={{ background: "var(--status-active)" }}
          />
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
