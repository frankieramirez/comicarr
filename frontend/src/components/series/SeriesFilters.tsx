import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from "@/components/ui/select";
import { useContentSources } from "@/hooks/useContentSources";

export type TypeFilter = "all" | "comic" | "manga" | "magazine";
export type ProgressFilter = "all" | "0" | "partial" | "100";
export type StatusFilter = "all" | "Active" | "Paused" | "Ended";

interface SeriesFiltersProps {
  typeFilter: TypeFilter;
  progressFilter: ProgressFilter;
  statusFilter: StatusFilter;
  onTypeChange: (value: TypeFilter) => void;
  onProgressChange: (value: ProgressFilter) => void;
  onStatusChange: (value: StatusFilter) => void;
  resultCount?: number;
  sortLabel?: string;
  /** Offer the magazine option; only shown once a series is cataloged as one. */
  hasMagazines?: boolean;
  /** Series per kind, shown inside the kind toggle. */
  typeCounts?: Partial<Record<TypeFilter, number>>;
}

interface ChipProps {
  label: string;
  value: string;
  active: boolean;
  onValueChange: (value: string) => void;
  options: { value: string; label: string }[];
}

function FilterChip({
  label,
  value,
  active,
  onValueChange,
  options,
}: ChipProps) {
  const display = options.find((o) => o.value === value)?.label ?? value;
  return (
    <div className="order-3">
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger
          aria-label={`${label}: ${display}`}
          className={`h-8 w-auto gap-1.5 rounded-control border px-2.5 text-[13px] shadow-none transition-colors [&_svg]:h-3.5 [&_svg]:w-3.5 ${
            active
              ? "border-border-emphasis bg-surface-3 text-foreground"
              : "border-border-subtle bg-surface-1 text-foreground hover:bg-surface-2"
          }`}
        >
          <span className="text-foreground-2">{label}</span>
          <span className="font-medium">{display}</span>
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value} className="text-[13px]">
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

export default function SeriesFilters({
  typeFilter,
  progressFilter,
  statusFilter,
  onTypeChange,
  onProgressChange,
  onStatusChange,
  resultCount,
  sortLabel,
  hasMagazines = false,
  typeCounts,
}: SeriesFiltersProps) {
  const { comicsEnabled, mangaEnabled } = useContentSources();
  const showManga = comicsEnabled && mangaEnabled;
  const showTypeFilter = showManga || hasMagazines;

  return (
    <div className="contents">
      {showTypeFilter && (
        <div
          role="group"
          aria-label="Kind"
          className="order-1 inline-flex items-center rounded-md border border-border-subtle bg-surface-1 p-0.5"
        >
          {(
            [
              ["all", "All"],
              ["comic", "Comics"],
              ...(showManga ? [["manga", "Manga"]] : []),
              ...(hasMagazines ? [["magazine", "Magazines"]] : []),
            ] as [TypeFilter, string][]
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={typeFilter === value}
              onClick={() => onTypeChange(value)}
              className={`inline-flex h-7 items-center gap-1.5 rounded-[5px] px-2.5 text-[13px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 ${
                typeFilter === value
                  ? "bg-surface-3 font-medium text-foreground"
                  : "text-foreground-2 hover:text-foreground"
              }`}
            >
              {label}
              {typeCounts?.[value] != null && (
                <span className="font-mono text-[11px] text-muted-foreground">
                  {typeCounts[value]}
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      <FilterChip
        label="Status"
        value={statusFilter}
        active={statusFilter !== "all"}
        onValueChange={(v) => onStatusChange(v as StatusFilter)}
        options={[
          { value: "all", label: "Any" },
          { value: "Active", label: "Active" },
          { value: "Paused", label: "Paused" },
          { value: "Ended", label: "Ended" },
        ]}
      />

      <FilterChip
        label="Progress"
        value={progressFilter}
        active={progressFilter !== "all"}
        onValueChange={(v) => onProgressChange(v as ProgressFilter)}
        options={[
          { value: "all", label: "Any" },
          { value: "0", label: "Not started" },
          { value: "partial", label: "In progress" },
          { value: "100", label: "Complete" },
        ]}
      />

      {(typeFilter !== "all" ||
        progressFilter !== "all" ||
        statusFilter !== "all") && (
        <button
          type="button"
          onClick={() => {
            onTypeChange("all");
            onProgressChange("all");
            onStatusChange("all");
          }}
          className="order-3 ml-1 px-1 text-[13px] text-foreground-2 underline-offset-2 hover:text-foreground hover:underline"
        >
          Clear
        </button>
      )}

      {(resultCount !== undefined || sortLabel) && (
        <div className="order-3 ml-auto flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
          {resultCount !== undefined && (
            <span>
              {resultCount} result{resultCount === 1 ? "" : "s"}
            </span>
          )}
          {resultCount !== undefined && sortLabel && (
            <span className="text-muted-foreground/50">·</span>
          )}
          {sortLabel && (
            <span>
              sort: <span className="text-foreground">{sortLabel}</span>
            </span>
          )}
        </div>
      )}
    </div>
  );
}
