import { plural, t } from "@lingui/core/macro";
import { LibraryBig } from "lucide-react";

interface ShelfChipProps {
  /** Print copies of this item. Zero shows a quiet "add" control. */
  count: number;
  /** What the copies are of, for the accessible name: "#64" or "Vol. 3". */
  label: string;
  onClick: () => void;
}

/** How many print copies of one issue or volume are on the shelf. Opens them. */
export function ShelfChip({ count, label, onClick }: ShelfChipProps) {
  const name =
    count === 0
      ? t`Add a print copy of ${label}`
      : plural(count, {
          one: `# print copy of ${label}`,
          other: `# print copies of ${label}`,
        });
  return (
    <button
      type="button"
      aria-label={name}
      title={name}
      data-testid="shelf-chip"
      onClick={onClick}
      className={
        count > 0
          ? "inline-flex h-5 items-center gap-1 rounded-control border border-border-strong px-1.5 font-mono text-[11px] text-foreground-2 transition-colors hover:text-foreground"
          : "inline-flex size-5 items-center justify-center rounded-control text-muted-foreground opacity-0 transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover/row:opacity-100 max-md:opacity-60"
      }
    >
      <LibraryBig aria-hidden="true" className="size-3" />
      {count > 0 ? count : null}
    </button>
  );
}
