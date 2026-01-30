import { useState, FormEvent } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import type { LucideIcon } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import ThemeToggle from '@/components/ThemeToggle';
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
} from '@/components/ui/sidebar';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  Home,
  Search,
  Calendar,
  ListTodo,
  Settings,
  LogOut,
  BookMarked,
  MessageSquare,
} from 'lucide-react';
import { Button } from '@/components/ui/button';

export default function AppSidebar() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { setOpenMobile } = useSidebar();
  const [searchQuery, setSearchQuery] = useState('');

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const handleSearchSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const trimmed = searchQuery.trim();
    if (trimmed.length >= 3) {
      navigate(`/search?q=${encodeURIComponent(trimmed)}&page=1`);
      setSearchQuery('');
      setOpenMobile(false);
    }
  };

  interface NavItem {
    path: string;
    label: string;
    icon: LucideIcon;
  }

  const navItems: NavItem[] = [
    { path: '/', label: 'Series', icon: Home },
    { path: '/upcoming', label: 'Upcoming', icon: Calendar },
    { path: '/wanted', label: 'Wanted', icon: ListTodo },
    { path: '/story-arcs', label: 'Story Arcs', icon: BookMarked },
  ];

  const isActive = (path: string): boolean => {
    if (path === '/') {
      return location.pathname === '/';
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
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link to="/" onClick={handleNavClick}>
                <MessageSquare className="w-6 h-6 text-primary" />
                <span className="text-xl font-bold gradient-brand">Mylar4</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarSeparator />

      {/* Search Section */}
      <div className="px-2 py-2">
        {/* Expanded: show input */}
        <form onSubmit={handleSearchSubmit} className="group-data-[collapsible=icon]:hidden">
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
                onClick={() => navigate('/search')}
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
      <SidebarContent>
        <SidebarMenu>
          {navItems.map(({ path, label, icon: Icon }) => (
            <SidebarMenuItem key={path}>
              <SidebarMenuButton
                asChild
                isActive={isActive(path)}
                tooltip={label}
              >
                <Link to={path} onClick={handleNavClick}>
                  <Icon className="w-4 h-4 opacity-80" />
                  <span>{label}</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>

        <SidebarSeparator className="mt-auto" />

        {/* Settings at bottom */}
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              asChild
              isActive={isActive('/settings')}
              tooltip="Settings"
            >
              <Link to="/settings" onClick={handleNavClick}>
                <Settings className="w-4 h-4 opacity-80" />
                <span>Settings</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarContent>

      {/* Footer with Theme Toggle and Logout */}
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <div className="flex items-center gap-2 px-2">
              <ThemeToggle />
              <Button
                variant="ghost"
                size="sm"
                onClick={handleLogout}
                className="flex-1 justify-start text-muted-foreground hover:text-foreground"
              >
                <LogOut className="w-4 h-4 mr-2" />
                Logout
              </Button>
            </div>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
