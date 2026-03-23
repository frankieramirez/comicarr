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
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Home,
  Search,
  Calendar,
  ListTodo,
  Settings,
  LogOut,
  BookMarked,
  Moon,
  Sun,
  FolderInput,
} from "lucide-react";

export default function AppSidebar() {
  const { logout } = useAuth();
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

  interface NavItem {
    path: string;
    label: string;
    icon: LucideIcon;
  }

  const navItems: NavItem[] = [
    { path: "/", label: "Series", icon: Home },
    { path: "/upcoming", label: "Upcoming", icon: Calendar },
    { path: "/wanted", label: "Wanted", icon: ListTodo },
    { path: "/story-arcs", label: "Story Arcs", icon: BookMarked },
    { path: "/import", label: "Import", icon: FolderInput },
  ];

  const isActive = (path: string): boolean => {
    if (path === "/") {
      return location.pathname === "/";
    }
    return location.pathname.startsWith(path);
  };

  const handleNavClick = () => {
    // Close mobile sidebar after navigation
    setOpenMobile(false);
  };

  return (
    <Sidebar collapsible="icon" variant="sidebar">
      {/* Header with Logo */}
      <SidebarHeader className="p-4">
        <SidebarMenu>
          <SidebarMenuItem>
            <Link
              to="/"
              onClick={handleNavClick}
              className="flex items-center py-2"
            >
              <Logo className="w-full max-h-10 text-foreground" />
            </Link>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      {/* Search Section */}
      <div className="px-3 pb-3">
        {/* Expanded: show input */}
        <form
          onSubmit={handleSearchSubmit}
          className="group-data-[collapsible=icon]:hidden"
        >
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <SidebarInput
              placeholder="Search comics..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9"
            />
          </div>
        </form>

        {/* Collapsed: show icon button with tooltip */}
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

      <SidebarSeparator />

      {/* Main Navigation */}
      <SidebarContent className="px-2 pt-2">
        <SidebarMenu>
          {navItems.map(({ path, label, icon: Icon }) => (
            <SidebarMenuItem key={path}>
              <SidebarMenuButton
                asChild
                isActive={isActive(path)}
                tooltip={label}
              >
                <Link to={path} onClick={handleNavClick}>
                  <Icon className="w-4 h-4" />
                  <span>{label}</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarContent>

      <SidebarSeparator />

      {/* Footer with Settings, Theme, and Logout */}
      <SidebarFooter className="px-2 pb-4">
        <SidebarMenu>
          {/* Settings */}
          <SidebarMenuItem>
            <SidebarMenuButton
              asChild
              isActive={isActive("/settings")}
              tooltip="Settings"
            >
              <Link to="/settings" onClick={handleNavClick}>
                <Settings className="w-4 h-4" />
                <span>Settings</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>

          {/* Theme Toggle */}
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
              <span>{theme === "light" ? "Dark mode" : "Light mode"}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>

          {/* Logout */}
          <SidebarMenuItem>
            <SidebarMenuButton onClick={handleLogout} tooltip="Logout">
              <LogOut className="w-4 h-4" />
              <span>Logout</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
