import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import ThemeToggle from '@/components/ThemeToggle';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarSeparator,
  useSidebar,
} from '@/components/ui/sidebar';
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

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const navItems = [
    { path: '/', label: 'Series', icon: Home },
    { path: '/search', label: 'Search', icon: Search },
    { path: '/upcoming', label: 'Upcoming', icon: Calendar },
    { path: '/wanted', label: 'Wanted', icon: ListTodo },
    { path: '/story-arcs', label: 'Story Arcs', icon: BookMarked },
  ];

  const isActive = (path) => {
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
