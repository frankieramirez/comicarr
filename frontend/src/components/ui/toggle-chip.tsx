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
 * Pressed filter/section chip. Active tint lives in classes so both themes
 * resolve `--primary`; `aria-pressed` is always set.
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
          "inline-flex shrink-0 items-center gap-1.5 rounded-full border transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
          pressed
            ? "border-primary bg-[color-mix(in_oklab,var(--primary)_12%,transparent)] text-foreground"
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
