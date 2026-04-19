import { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  meta?: ReactNode;
  actions?: ReactNode;
  className?: string;
}

/**
 * Standard Direction B page header — 18/semibold title + mono meta on the
 * left, optional actions on the right, hairline divider below.
 */
export default function PageHeader({
  title,
  meta,
  actions,
  className = "",
}: PageHeaderProps) {
  return (
    <div
      className={`px-5 py-3.5 border-b border-border flex items-center gap-3 ${className}`}
    >
      <div className="min-w-0">
        <div className="text-[18px] font-semibold tracking-tight leading-none">
          {title}
        </div>
        {meta != null && (
          <div className="font-mono text-[11px] text-muted-foreground mt-1.5 truncate">
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
      className="px-5 pt-3 border-b border-border flex items-end gap-6"
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
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className="relative pb-3 -mb-px font-mono text-[11px] tracking-[0.1em] uppercase flex items-center gap-2 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      style={{
        color: active ? "var(--foreground)" : "var(--muted-foreground)",
      }}
    >
      <span>{label}</span>
      {meta != null && (
        <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
          {meta}
        </span>
      )}
      <span
        className="absolute left-0 right-0 bottom-0 h-[2px]"
        style={{ background: active ? "var(--primary)" : "transparent" }}
      />
    </button>
  );
}
