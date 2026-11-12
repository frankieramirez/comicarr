import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, RefreshCw } from "lucide-react";
import type { PanelState } from "@/lib/panelState";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * The shared shell every dashboard panel renders through.
 *
 * A panel has exactly the four states of `PanelState` and the shell owns all
 * of them, so no panel can invent a fifth — in particular, none can render a
 * broken source as an empty one. `unavailable` carries a retry scoped to that
 * panel alone, and `loading` renders a skeleton in the panel's final position
 * so a slow source resolving does not shift its neighbours
 * (docs/architecture/dashboard-spec.md §5).
 */

/** An honest sentence in the panel's own voice — never a blank card. */
export function PanelNote({ children }: { children: ReactNode }) {
  return <div className="py-2 text-sm text-foreground-2">{children}</div>;
}

/**
 * v2 section heading. `main` sections (left column) use a 15px title with a
 * mono count; `rail` sections use a small uppercase label. Both end in at
 * most one quiet link out to the full view.
 */
export function SectionHeader({
  title,
  meta,
  action,
  variant = "main",
}: {
  title: string;
  meta?: ReactNode;
  action?: { label: string; to: string };
  variant?: "main" | "rail";
}) {
  return (
    <div className="mb-2 flex items-center justify-between gap-3">
      <div className="flex min-w-0 items-baseline gap-2.5">
        <h2
          className={
            variant === "main"
              ? "shrink-0 whitespace-nowrap text-[15px] font-semibold text-foreground"
              : "shrink-0 whitespace-nowrap text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground"
          }
        >
          {title}
        </h2>
        {meta != null && (
          <span className="truncate font-mono text-xs text-muted-foreground max-sm:hidden">
            {meta}
          </span>
        )}
      </div>
      {action && (
        <Link
          to={action.to}
          className="inline-flex shrink-0 items-center gap-0.5 text-[13px] text-foreground-2 hover:text-foreground"
        >
          {action.label}
          <ChevronRight className="size-3.5 text-muted-foreground" />
        </Link>
      )}
    </div>
  );
}

/**
 * A failed panel says so and offers its own retry. The label names the source
 * so two unavailable panels on one page stay distinguishable.
 */
export function PanelUnavailable({
  label,
  onRetry,
  isRetrying = false,
}: {
  label: string;
  onRetry: () => void;
  isRetrying?: boolean;
}) {
  return (
    <div className="flex items-center gap-2.5 py-2 text-sm">
      <span style={{ color: "var(--status-error)" }}>{label} unavailable</span>
      <button
        type="button"
        onClick={onRetry}
        disabled={isRetrying}
        aria-label={`Retry ${label}`}
        className="inline-flex h-7 items-center gap-1.5 rounded-control border border-border-strong bg-surface-2 px-2 text-xs text-foreground-2 hover:text-foreground disabled:opacity-50"
      >
        <RefreshCw className={`w-3 h-3 ${isRetrying ? "animate-spin" : ""}`} />
        {isRetrying ? "retrying…" : "retry"}
      </button>
    </div>
  );
}

/**
 * Placeholder rows at the height of the real ones. Sized by the caller so the
 * skeleton occupies the space the resolved content will take.
 */
export function PanelSkeleton({
  rows,
  rowHeight = 28,
}: {
  rows: number;
  rowHeight?: number;
}) {
  return (
    <div className="py-1.5" aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => (
        <div
          key={index}
          className="flex items-center"
          style={{ height: rowHeight }}
        >
          <Skeleton className="h-2.5 w-full rounded-sm" />
        </div>
      ))}
    </div>
  );
}

/**
 * Renders the one branch the state selects. Content is a thunk so a panel
 * never has to build rows out of data it does not have yet.
 */
export function PanelBody({
  state,
  label,
  skeleton,
  empty,
  onRetry,
  isRetrying,
  children,
}: {
  state: PanelState;
  label: string;
  skeleton: ReactNode;
  empty: ReactNode;
  onRetry: () => void;
  isRetrying?: boolean;
  children: () => ReactNode;
}) {
  if (state === "loading") return <>{skeleton}</>;
  if (state === "unavailable") {
    return (
      <PanelUnavailable
        label={label}
        onRetry={onRetry}
        isRetrying={isRetrying}
      />
    );
  }
  if (state === "empty") return <PanelNote>{empty}</PanelNote>;
  return <>{children()}</>;
}
