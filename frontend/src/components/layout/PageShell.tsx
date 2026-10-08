import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type PageShellVariant = "full-bleed" | "centred";

interface PageShellProps {
  header?: ReactNode;
  children: ReactNode;
  variant?: PageShellVariant;
  className?: string;
}

/**
 * Page-owned scroll shell. Full-bleed is the default: a pinned header slot
 * and an inner scroller. Pages that want Layout's old padded column opt into
 * `variant="centred"`. Layout still decides overflow from FULL_BLEED_* until
 * every route renders a PageShell.
 */
export default function PageShell({
  header,
  children,
  variant = "full-bleed",
  className,
}: PageShellProps) {
  return (
    <div
      data-testid="page-shell"
      data-variant={variant}
      className={cn(
        "page-transition flex h-full min-h-0 min-w-0 flex-col",
        variant === "centred" &&
          "mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 lg:px-8",
        className,
      )}
    >
      {header != null ? (
        <div data-testid="page-shell-header" className="shrink-0">
          {header}
        </div>
      ) : null}
      <div
        data-testid="page-shell-body"
        className="min-h-0 min-w-0 flex-1 overflow-auto"
      >
        {children}
      </div>
    </div>
  );
}
