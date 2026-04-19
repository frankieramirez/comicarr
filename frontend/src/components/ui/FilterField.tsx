import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";
import { Search, Loader2 } from "lucide-react";
import { Kbd } from "@/components/ui/kbd";

interface FilterFieldProps extends Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "size"
> {
  /** Optional keyboard shortcut hint rendered on the right (e.g. "/"). */
  shortcut?: string;
  /** Show an inline spinner on the right (replaces shortcut hint). */
  loading?: boolean;
  /** Width cap. Defaults to `md` (28rem). Pass `"full"` for no cap. */
  widthCap?: "sm" | "md" | "lg" | "xl" | "full";
  /** Extra nodes rendered to the right of the input (before shortcut). */
  trailing?: ReactNode;
  className?: string;
}

const CAP_CLASS: Record<NonNullable<FilterFieldProps["widthCap"]>, string> = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-lg",
  xl: "max-w-xl",
  full: "",
};

/**
 * Canonical Direction B filter/search input.
 *
 * 28px tall, 12px text, left-aligned 14px search icon, optional `/` kbd
 * hint on the right. Used across Library filter, Wanted filter, Story
 * Arcs search, etc. so every surface feels the same.
 */
const FilterField = forwardRef<HTMLInputElement, FilterFieldProps>(
  function FilterField(
    {
      shortcut,
      loading,
      widthCap = "md",
      trailing,
      className = "",
      ...inputProps
    },
    ref,
  ) {
    return (
      <div
        className={`flex items-center gap-2 flex-1 ${CAP_CLASS[widthCap]} h-8 px-2.5 rounded-[5px] border bg-card focus-within:border-[var(--ring)] focus-within:ring-2 focus-within:ring-ring/40 transition-[box-shadow,border-color] ${className}`}
        style={{ borderColor: "var(--border)" }}
      >
        <Search
          className="w-3.5 h-3.5 shrink-0"
          style={{ color: "var(--muted-foreground)" }}
        />
        <input
          ref={ref}
          type="text"
          {...inputProps}
          className="flex-1 min-w-0 bg-transparent outline-none text-[12px] placeholder:text-[var(--text-muted)]"
        />
        {trailing}
        {loading ? (
          <Loader2
            className="w-3.5 h-3.5 shrink-0 animate-spin"
            style={{ color: "var(--muted-foreground)" }}
          />
        ) : shortcut ? (
          <Kbd>{shortcut}</Kbd>
        ) : null}
      </div>
    );
  },
);

export default FilterField;
