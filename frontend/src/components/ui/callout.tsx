import * as React from "react";
import { cn } from "@/lib/utils";

const TONE = {
  error: {
    role: "alert" as const,
    className:
      "bg-[var(--status-error-bg)] text-[var(--status-error)] border-[color-mix(in_oklab,var(--status-error)_30%,transparent)]",
  },
  warning: {
    role: "status" as const,
    className:
      "bg-[var(--status-paused-bg)] text-[var(--status-paused)] border-[color-mix(in_oklab,var(--status-paused)_30%,transparent)]",
  },
  success: {
    role: "status" as const,
    className:
      "bg-[var(--status-active-bg)] text-[var(--status-active)] border-[color-mix(in_oklab,var(--status-active)_30%,transparent)]",
  },
  info: {
    role: "status" as const,
    className:
      "bg-[var(--status-wanted-bg)] text-[var(--status-wanted)] border-[color-mix(in_oklab,var(--status-wanted)_30%,transparent)]",
  },
} as const;

export type CalloutTone = keyof typeof TONE;

export interface CalloutProps extends React.HTMLAttributes<HTMLDivElement> {
  tone?: CalloutTone;
}

/**
 * Status-coloured banner. Tokens live in classes so both themes resolve;
 * error is `role="alert"`, everything else `role="status"`.
 */
const Callout = React.forwardRef<HTMLDivElement, CalloutProps>(
  ({ tone = "info", className, ...props }, ref) => {
    const spec = TONE[tone];
    return (
      <div
        ref={ref}
        role={spec.role}
        className={cn("rounded-lg border p-4", spec.className, className)}
        {...props}
      />
    );
  },
);
Callout.displayName = "Callout";

export { Callout };
