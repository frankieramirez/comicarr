import * as React from "react";
import { cn } from "@/lib/utils";

const sizeClass = {
  xs: "font-mono text-[10px] px-2 py-0.5",
  sm: "font-mono text-[11px] px-2.5 py-1",
  md: "text-[12px] px-2.5 py-1",
} as const;

export interface ToggleChipProps extends Omit<
  React.ButtonHTMLAttributes<HTMLButtonElement>,
  "onClick"
> {
  pressed: boolean;
  onPressedChange: (pressed: boolean) => void;
  size?: keyof typeof sizeClass;
}

/**
 * Pressed filter/section chip. Pressed state is a neutral raised surface (v2: orange is accents only); `aria-pressed` is always set.
 */
const ToggleChip = React.forwardRef<HTMLButtonElement, ToggleChipProps>(
  (
    {
      pressed,
      onPressedChange,
      size = "sm",
      className,
      type = "button",
      children,
      ...props
    },
    ref,
  ) => {
    return (
      <button
        ref={ref}
        type={type}
        aria-pressed={pressed}
        onClick={() => onPressedChange(!pressed)}
        className={cn(
          "inline-flex shrink-0 items-center gap-1.5 rounded-control border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
          pressed
            ? "border-border-emphasis bg-surface-3 text-foreground"
            : "border-border bg-transparent text-muted-foreground hover:text-foreground",
          sizeClass[size],
          className,
        )}
        {...props}
      >
        {children}
      </button>
    );
  },
);
ToggleChip.displayName = "ToggleChip";

export { ToggleChip };
