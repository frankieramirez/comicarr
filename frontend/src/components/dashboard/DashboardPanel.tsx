import { type ReactNode } from "react";
import { RefreshCw } from "lucide-react";
import type { PanelState } from "@/lib/panelState";

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
  return (
    <div className="font-mono text-[11px] text-muted-foreground py-3">
      {children}
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
    <div className="flex items-center gap-2.5 py-3 font-mono text-[11px]">
      <span style={{ color: "var(--status-error)" }}>{label} unavailable</span>
      <button
        type="button"
        onClick={onRetry}
        disabled={isRetrying}
        aria-label={`Retry ${label}`}
        className="inline-flex items-center gap-1.5 px-2 py-1 rounded-[5px] border border-border text-muted-foreground hover:text-foreground disabled:opacity-50"
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
          <div className="h-2.5 w-full animate-pulse rounded-[2px] bg-primary/10" />
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
