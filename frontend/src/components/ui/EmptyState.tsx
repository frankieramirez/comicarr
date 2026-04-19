import { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  BookOpen,
  Calendar,
  Search,
  Library,
  ListTodo,
  ArrowRight,
  type LucideIcon,
} from "lucide-react";

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
  eyebrow?: string;
  title?: string;
  description?: string;
  action?: EmptyStateAction;
  children?: ReactNode;
}

const VARIANT_CONFIGS: Record<
  Exclude<EmptyStateVariant, "custom">,
  {
    icon: LucideIcon;
    eyebrow: string;
    title: string;
    description: string;
    action?: EmptyStateAction;
  }
> = {
  library: {
    icon: Library,
    eyebrow: "LIBRARY · EMPTY",
    title: "No series tracked yet",
    description:
      "Search the providers you've connected and add series to start monitoring issues.",
    action: { label: "Add series", to: "/search" },
  },
  wanted: {
    icon: ListTodo,
    eyebrow: "WANTED · EMPTY",
    title: "No wanted issues",
    description:
      "Mark issues as wanted from a series and Comicarr will search for them automatically.",
  },
  upcoming: {
    icon: Calendar,
    eyebrow: "UPCOMING · EMPTY",
    title: "No releases this week",
    description:
      "Add more series to surface upcoming issues on the weekly schedule.",
    action: { label: "Browse series", to: "/search" },
  },
  search: {
    icon: Search,
    eyebrow: "SEARCH · NO MATCH",
    title: "No results found",
    description:
      "Adjust the query or filters — try the series title, author, or publisher.",
  },
  issues: {
    icon: BookOpen,
    eyebrow: "ISSUES · EMPTY",
    title: "No issues indexed",
    description:
      "This series has no issues tracked yet. Refresh to pull the latest metadata.",
  },
  "story-arcs": {
    icon: BookOpen,
    eyebrow: "ARCS · EMPTY",
    title: "No story arcs tracked",
    description:
      "Search for arcs above to track reading progress across series and issues.",
  },
};

export default function EmptyState({
  variant = "custom",
  icon: CustomIcon,
  eyebrow: customEyebrow,
  title: customTitle,
  description: customDescription,
  action: customAction,
  children,
}: EmptyStateProps) {
  const config = variant !== "custom" ? VARIANT_CONFIGS[variant] : null;

  const Icon = CustomIcon || config?.icon || BookOpen;
  const eyebrow = customEyebrow || config?.eyebrow || "EMPTY";
  const title = customTitle || config?.title || "Nothing here yet";
  const description = customDescription || config?.description || "";
  const action = customAction || config?.action;

  const isOutline = action?.variant === "outline";
  const cta = action && (
    <span
      className={`inline-flex items-center gap-2 px-3.5 py-2 rounded-[5px] text-[12px] font-semibold ${
        isOutline ? "border" : ""
      }`}
      style={
        isOutline
          ? {
              borderColor: "var(--border)",
              background: "transparent",
              color: "var(--foreground)",
            }
          : {
              background: "var(--primary)",
              color: "var(--primary-foreground)",
            }
      }
    >
      {action.label}
      <ArrowRight className="w-3.5 h-3.5" />
    </span>
  );

  return (
    <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
      <div
        className="w-11 h-11 rounded-full grid place-items-center mb-5"
        style={{
          border: "1px solid var(--border)",
          background: "var(--secondary)",
        }}
      >
        <Icon
          className="w-4 h-4"
          style={{ color: "var(--muted-foreground)" }}
          strokeWidth={1.5}
        />
      </div>
      <div className="font-mono text-[10px] tracking-[0.12em] text-muted-foreground mb-2">
        {eyebrow}
      </div>
      <h3 className="text-[15px] font-semibold text-foreground mb-1.5 tracking-tight">
        {title}
      </h3>
      {description && (
        <p className="text-[12px] text-muted-foreground max-w-[340px] mb-5 leading-relaxed">
          {description}
        </p>
      )}
      {action &&
        (action.to ? (
          <Link
            to={action.to}
            className="rounded-[5px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            {cta}
          </Link>
        ) : action.onClick ? (
          <button
            type="button"
            onClick={action.onClick}
            className="rounded-[5px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            {cta}
          </button>
        ) : null)}
      {children}
    </div>
  );
}
