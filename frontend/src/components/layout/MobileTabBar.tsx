import { Link, useLocation } from "react-router-dom";
import {
  Activity,
  BookOpen,
  LayoutDashboard,
  ListTodo,
  Menu,
  type LucideIcon,
} from "lucide-react";
import { useSidebar } from "@/components/ui/sidebar";
import { useActivityStatus } from "@/hooks/useActivityStatus";
import { cn } from "@/lib/utils";

interface Tab {
  path: string;
  label: string;
  icon: LucideIcon;
  count?: number;
}

function isActive(pathname: string, path: string) {
  if (path === "/") return pathname === "/";
  if (path === "/library") {
    return (
      pathname.startsWith("/library") ||
      pathname.startsWith("/series") ||
      pathname.startsWith("/story-arcs")
    );
  }
  return pathname.startsWith(path);
}

/**
 * The phone's primary navigation (v2 mobile designs): four destinations and
 * More, which opens the full sidebar as a sheet for everything else. Below
 * `md` only; the sidebar is the desktop nav.
 */
export default function MobileTabBar() {
  const { pathname } = useLocation();
  const { setOpenMobile, openMobile } = useSidebar();
  const { data: status } = useActivityStatus();
  const attention = status?.attention ?? 0;

  const tabs: Tab[] = [
    { path: "/", label: "Home", icon: LayoutDashboard },
    { path: "/library", label: "Library", icon: BookOpen },
    { path: "/wanted", label: "Wanted", icon: ListTodo },
    { path: "/activity", label: "Activity", icon: Activity, count: attention },
  ];
  const anyActive = tabs.some((tab) => isActive(pathname, tab.path));

  const itemClass = (active: boolean) =>
    cn(
      "relative flex flex-1 flex-col items-center gap-1 pt-2 pb-1.5 text-[11px]",
      active ? "text-foreground" : "text-muted-foreground",
    );

  return (
    <nav
      aria-label="Primary"
      className="flex shrink-0 border-t border-border-subtle bg-background pb-[env(safe-area-inset-bottom)] md:hidden"
      data-testid="mobile-tab-bar"
    >
      {tabs.map(({ path, label, icon: Icon, count }) => {
        const active = isActive(pathname, path);
        return (
          <Link
            key={path}
            to={path}
            aria-current={active ? "page" : undefined}
            className={itemClass(active)}
          >
            <span className="relative">
              <Icon className="size-[22px]" strokeWidth={1.6} />
              {count != null && count > 0 && (
                <span
                  className="absolute -top-1.5 left-3.5 min-w-[18px] rounded-full px-1 text-center font-mono text-[10px] leading-[16px] font-semibold"
                  style={{
                    background: "var(--status-error)",
                    color: "var(--background)",
                  }}
                  aria-label={`${count} need you`}
                >
                  {count > 99 ? "99+" : count}
                </span>
              )}
            </span>
            {label}
          </Link>
        );
      })}
      <button
        type="button"
        onClick={() => setOpenMobile(true)}
        aria-expanded={openMobile}
        className={itemClass(!anyActive)}
      >
        <Menu className="size-[22px]" strokeWidth={1.6} />
        More
      </button>
    </nav>
  );
}
