import * as React from "react";
import { cn } from "@/lib/utils";

const TONE = {
  error: {
    role: "alert" as const,
    className:
      "bg-[var(--status-error-bg)] border-[color-mix(in_oklab,var(--status-error)_30%,transparent)] [&_svg]:text-[var(--status-error)]",
  },
  warning: {
    role: "alert" as const,
    className:
      "bg-[var(--status-paused-bg)] border-[color-mix(in_oklab,var(--status-paused)_30%,transparent)] [&_svg]:text-[var(--status-paused)]",
  },
  success: {
    role: "status" as const,
    className:
      "bg-[var(--status-active-bg)] border-[color-mix(in_oklab,var(--status-active)_30%,transparent)] [&_svg]:text-[var(--status-active)]",
  },
  info: {
    role: "status" as const,
    className:
      "bg-[var(--status-wanted-bg)] border-[color-mix(in_oklab,var(--status-wanted)_30%,transparent)] [&_svg]:text-[var(--status-wanted)]",
  },
} as const;

export type CalloutTone = keyof typeof TONE;

export interface CalloutProps extends React.HTMLAttributes<HTMLDivElement> {
  tone?: CalloutTone;
}

/**
 * Status-coloured banner. Tone applies to fill, border, and icon; body copy
 * stays foreground. Error and warning are `role="alert"`.
 */
const Callout = React.forwardRef<HTMLDivElement, CalloutProps>(
  ({ tone = "info", className, ...props }, ref) => {
    const spec = TONE[tone];
    return (
      <div
        ref={ref}
        role={spec.role}
        className={cn(
          "rounded-lg border p-4 text-foreground",
          spec.className,
          className,
        )}
        {...props}
      />
    );
  },
);
Callout.displayName = "Callout";

export { Callout };
