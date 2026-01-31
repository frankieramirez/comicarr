import * as React from "react";
import { cn } from "@/lib/utils";

type BadgeVariant =
  | "default"
  | "secondary"
  | "outline"
  | "active"
  | "paused"
  | "ended"
  | "error"
  | "wanted"
  | "downloaded"
  | "skipped";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant = "default", ...props }, ref) => {
    const variants: Record<BadgeVariant, string> = {
      default: "bg-muted text-muted-foreground",
      secondary: "bg-secondary text-secondary-foreground",
      outline: "border border-input bg-background text-foreground",
      active: "bg-[var(--status-active-bg)] text-[var(--status-active)]",
      paused: "bg-[var(--status-paused-bg)] text-[var(--status-paused)]",
      ended: "bg-[var(--status-ended-bg)] text-[var(--status-ended)]",
      error: "bg-[var(--status-error-bg)] text-[var(--status-error)]",
      wanted: "bg-[var(--status-wanted-bg)] text-[var(--status-wanted)]",
      downloaded:
        "bg-[var(--status-downloaded-bg)] text-[var(--status-downloaded)]",
      skipped: "bg-[var(--status-skipped-bg)] text-[var(--status-skipped)]",
    };

    return (
      <span
        ref={ref}
        className={cn(
          "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold transition-all hover:scale-105",
          variants[variant],
          className,
        )}
        {...props}
      />
    );
  },
);
Badge.displayName = "Badge";

export { Badge };
