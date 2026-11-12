import { type ReactNode, useEffect, useRef } from "react";

interface PageHeaderProps {
  title: string;
  meta?: ReactNode;
  actions?: ReactNode;
  className?: string;
}

/**
 * v2 page header: 24/semibold title with a plain-language subtitle on the
 * left, at most one primary action on the right. No divider; the content
 * below brings its own hairlines.
 */
export default function PageHeader({
  title,
  meta,
  actions,
  className = "",
}: PageHeaderProps) {
  return (
    <div
      data-testid="page-header"
      className={`shrink-0 px-8 pt-6 pb-4 flex items-end gap-3 ${className}`}
    >
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight leading-tight">
          {title}
        </h1>
        {meta != null && (
          <div
            data-testid="page-header-meta"
            className="mt-1 truncate text-sm text-foreground-2"
          >
            {meta}
          </div>
        )}
      </div>
      {actions != null && (
        <div className="ml-auto flex items-center gap-2">{actions}</div>
      )}
    </div>
  );
}

interface TabRowProps {
  children: ReactNode;
  ariaLabel?: string;
}

/**
 * Row of page-level view toggles. These intentionally use plain button
 * semantics with `aria-pressed` (see Tab) rather than the full ARIA tab
 * pattern — there are no separate tabpanel elements with focus/arrow-key
 * navigation, so `role="tablist"` would over-promise.
 */
export function TabRow({ children, ariaLabel }: TabRowProps) {
  return (
    <div
      role="group"
      aria-label={ariaLabel ?? "View toggles"}
      className="shrink-0 mx-8 border-b border-border-subtle flex items-end gap-6 max-md:gap-5 max-md:overflow-x-auto max-md:[scrollbar-width:none]"
    >
      {children}
    </div>
  );
}

interface TabProps {
  active: boolean;
  label: string;
  onClick: () => void;
  meta?: ReactNode;
}

export function Tab({ active, label, onClick, meta }: TabProps) {
  const ref = useRef<HTMLButtonElement>(null);
  const hasMeta = meta != null;
  // On phones the row scrolls sideways; keep the current tab in view.
  useEffect(() => {
    if (active)
      ref.current?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [active, hasMeta]);
  return (
    <button
      ref={ref}
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`relative shrink-0 whitespace-nowrap pb-2.5 -mb-px text-sm font-medium flex items-center gap-1.5 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 ${
        active ? "text-foreground" : "text-foreground-2 hover:text-foreground"
      }`}
    >
      <span>{label}</span>
      {meta != null && (
        <span className="font-mono text-xs text-muted-foreground">{meta}</span>
      )}
      <span
        className={`absolute left-0 right-0 bottom-0 h-0.5 ${
          active ? "bg-primary" : "bg-transparent"
        }`}
      />
    </button>
  );
}
