import { ChevronDown } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from "@/components/ui/select";
import { useContentSources } from "@/hooks/useContentSources";

export type TypeFilter = "all" | "comic" | "manga";
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
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger
        className={`h-auto py-[3px] px-2 rounded-full font-mono text-[11px] gap-1.5 w-auto shadow-none transition-colors ${
          active
            ? "border-primary/60 text-primary bg-primary/10"
            : "border-border text-muted-foreground hover:text-foreground"
        }`}
      >
        <span className="text-muted-foreground/60">{label}:</span>
        <span>{display}</span>
        <ChevronDown className="w-3 h-3 opacity-60" />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem
            key={o.value}
            value={o.value}
            className="font-mono text-xs"
          >
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
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
}: SeriesFiltersProps) {
  const { comicsEnabled, mangaEnabled } = useContentSources();
  const showTypeFilter = comicsEnabled && mangaEnabled;

  return (
    <div className="flex flex-wrap items-center gap-2 font-mono text-[11px]">
      <span className="text-muted-foreground/60 uppercase tracking-wider pr-1">
        filter
      </span>

      {showTypeFilter && (
        <FilterChip
          label="type"
          value={typeFilter}
          active={typeFilter !== "all"}
          onValueChange={(v) => onTypeChange(v as TypeFilter)}
          options={[
            { value: "all", label: "all" },
            { value: "comic", label: "comic" },
            { value: "manga", label: "manga" },
          ]}
        />
      )}

      <FilterChip
        label="status"
        value={statusFilter}
        active={statusFilter !== "all"}
        onValueChange={(v) => onStatusChange(v as StatusFilter)}
        options={[
          { value: "all", label: "any" },
          { value: "Active", label: "active" },
          { value: "Paused", label: "paused" },
          { value: "Ended", label: "ended" },
        ]}
      />

      <FilterChip
        label="progress"
        value={progressFilter}
        active={progressFilter !== "all"}
        onValueChange={(v) => onProgressChange(v as ProgressFilter)}
        options={[
          { value: "all", label: "any" },
          { value: "0", label: "not started" },
          { value: "partial", label: "in progress" },
          { value: "100", label: "complete" },
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
          className="text-muted-foreground/60 hover:text-foreground ml-1 px-1"
        >
          clear
        </button>
      )}

      {(resultCount !== undefined || sortLabel) && (
        <div className="ml-auto flex items-center gap-1.5 text-muted-foreground">
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
