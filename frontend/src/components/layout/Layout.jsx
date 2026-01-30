import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { Button } from '@/components/ui/button';
import ThemeToggle from '@/components/ThemeToggle';
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

export default function Layout({ children }) {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

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
    { path: '/settings', label: 'Settings', icon: Settings },
  ];

  const isActive = (path) => {
    if (path === '/') {
      return location.pathname === '/';
    }
    return location.pathname.startsWith(path);
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Top Navigation */}
      <nav className="glass-nav sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            <div className="flex">
              {/* Logo */}
              <Link to="/" className="flex items-center px-2 space-x-2 group">
                <MessageSquare className="w-6 h-6 text-primary" />
                <span className="text-xl font-bold gradient-brand hover:scale-105 transition-transform">
                  Mylar4
                </span>
              </Link>

              {/* Navigation Links */}
              <div className="hidden sm:ml-8 sm:flex sm:space-x-1">
                {navItems.map(({ path, label, icon: Icon }) => (
                  <Link
                    key={path}
                    to={path}
                    className={`inline-flex items-center px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 ${
                      isActive(path)
                        ? 'text-primary bg-primary/10'
                        : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
                    }`}
                  >
                    <Icon className="w-4 h-4 mr-2 opacity-80" />
                    {label}
                  </Link>
                ))}
              </div>
            </div>

            {/* Right side - Theme Toggle & Logout */}
            <div className="flex items-center space-x-1">
              <ThemeToggle />
              <Button
                variant="ghost"
                size="sm"
                onClick={handleLogout}
                className="text-muted-foreground hover:text-foreground"
              >
                <LogOut className="w-4 h-4 mr-2" />
                Logout
              </Button>
            </div>
          </div>
        </div>

        {/* Mobile Navigation */}
        <div className="sm:hidden border-t border-border/50">
          <div className="flex overflow-x-auto scrollbar-hide">
            {navItems.map(({ path, label, icon: Icon }) => (
              <Link
                key={path}
                to={path}
                className={`flex-1 flex flex-col items-center px-3 py-3 text-xs font-medium whitespace-nowrap transition-colors ${
                  isActive(path)
                    ? 'text-primary bg-primary/10'
                    : 'text-muted-foreground'
                }`}
              >
                <Icon className="w-5 h-5 mb-1 opacity-80" />
                {label}
              </Link>
            ))}
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {children}
      </main>
    </div>
  );
}
