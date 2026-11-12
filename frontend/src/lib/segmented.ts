/**
 * The segmented control: a quiet track holding mutually exclusive buttons.
 * Each button sets `aria-pressed`; the pressed look keys off that attribute,
 * so callers never pick classes by state.
 *
 * Use it for a filter or view switch with two to five options. For page-level
 * navigation use `TabRow`.
 */
export const SEGMENTED_GROUP =
  "inline-flex items-center rounded-md border border-border-subtle bg-surface-1 p-0.5";

export const SEGMENTED_ITEM =
  "inline-flex h-7 items-center gap-1.5 rounded-control px-2.5 text-[13px] text-foreground-2 transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 aria-pressed:bg-surface-3 aria-pressed:font-medium aria-pressed:text-foreground";
