import { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  BookOpen,
  Calendar,
  Search,
  Library,
  ListTodo,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";

type EmptyStateVariant =
  | "library"
  | "wanted"
  | "upcoming"
  | "search"
  | "issues"
  | "story-arcs"
  | "custom";

interface EmptyStateAction {
  label: string;
  to?: string;
  onClick?: () => void;
  variant?: "default" | "outline";
}

interface EmptyStateProps {
  variant?: EmptyStateVariant;
  icon?: LucideIcon;
  title?: string;
  description?: string;
  action?: EmptyStateAction;
  children?: ReactNode;
}

const VARIANT_CONFIGS: Record<
  Exclude<EmptyStateVariant, "custom">,
  { icon: LucideIcon; title: string; description: string; action?: EmptyStateAction }
> = {
  library: {
    icon: Library,
    title: "Your library is empty",
    description: "Search for comics to add them to your library and start tracking your collection.",
    action: { label: "Search Comics", to: "/search" },
  },
  wanted: {
    icon: ListTodo,
    title: "No wanted issues",
    description: "Mark issues as wanted from your series to see them here. Mylar will automatically search for them.",
  },
  upcoming: {
    icon: Calendar,
    title: "No upcoming releases",
    description: "Add more series to your library to see upcoming releases for this week.",
    action: { label: "Browse Series", to: "/search" },
  },
  search: {
    icon: Search,
    title: "No results found",
    description: "Try adjusting your search terms or filters to find what you're looking for.",
  },
  issues: {
    icon: BookOpen,
    title: "No issues found",
    description: "This series doesn't have any issues yet. Try refreshing the series data.",
  },
  "story-arcs": {
    icon: BookOpen,
    title: "Story Arcs Coming Soon",
    description: "Track your favorite story arcs across multiple series. This feature is under development.",
  },
};

/**
 * Flexible empty state component for various contexts
 */
export default function EmptyState({
  variant = "custom",
  icon: CustomIcon,
  title: customTitle,
  description: customDescription,
  action: customAction,
  children,
}: EmptyStateProps) {
  const config = variant !== "custom" ? VARIANT_CONFIGS[variant] : null;

  const Icon = CustomIcon || config?.icon || BookOpen;
  const title = customTitle || config?.title || "Nothing here yet";
  const description = customDescription || config?.description || "";
  const action = customAction || config?.action;

  return (
    <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
      <div className="bg-muted rounded-full p-6 mb-6">
        <Icon className="w-12 h-12 text-muted-foreground" />
      </div>
      <h3 className="text-xl font-semibold text-foreground mb-2">{title}</h3>
      <p className="text-muted-foreground max-w-md mb-6">{description}</p>
      {action && (
        action.to ? (
          <Link to={action.to}>
            <Button variant={action.variant || "default"}>
              {action.label}
            </Button>
          </Link>
        ) : action.onClick ? (
          <Button variant={action.variant || "default"} onClick={action.onClick}>
            {action.label}
          </Button>
        ) : null
      )}
      {children}
    </div>
  );
}
