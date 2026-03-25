import { Book, BookOpen, Library } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
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
  counts?: {
    type: Record<TypeFilter, number>;
    progress: Record<ProgressFilter, number>;
    status: Record<StatusFilter, number>;
  };
}

export default function SeriesFilters({
  typeFilter,
  progressFilter,
  statusFilter,
  onTypeChange,
  onProgressChange,
  onStatusChange,
  counts,
}: SeriesFiltersProps) {
  const { comicsEnabled, mangaEnabled } = useContentSources();
  const showTypeFilter = comicsEnabled && mangaEnabled;

  // Helper to format count
  const formatCount = (count: number | undefined) => {
    if (count === undefined || count === 0) return "";
    return ` (${count})`;
  };

  return (
    <div className="flex flex-wrap gap-3 items-center">
      {/* Type Filter - only show when both content sources are enabled */}
      {showTypeFilter && (
        <div className="inline-flex rounded-lg border border-border p-0.5 bg-muted/50">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onTypeChange("all")}
            className={`h-8 px-3 rounded-md text-sm font-medium transition-colors ${
              typeFilter === "all"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Library className="w-4 h-4 mr-1.5" />
            All{formatCount(counts?.type.all)}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onTypeChange("comic")}
            className={`h-8 px-3 rounded-md text-sm font-medium transition-colors ${
              typeFilter === "comic"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Book className="w-4 h-4 mr-1.5" />
            Comics{formatCount(counts?.type.comic)}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onTypeChange("manga")}
            className={`h-8 px-3 rounded-md text-sm font-medium transition-colors ${
              typeFilter === "manga"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <BookOpen className="w-4 h-4 mr-1.5" />
            Manga{formatCount(counts?.type.manga)}
          </Button>
        </div>
      )}

      {/* Progress Filter - Dropdown */}
      <Select
        value={progressFilter}
        onValueChange={(value) => onProgressChange(value as ProgressFilter)}
      >
        <SelectTrigger className="w-[140px] h-9">
          <SelectValue placeholder="Progress" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All Progress</SelectItem>
          <SelectItem value="0">
            Not Started{formatCount(counts?.progress["0"])}
          </SelectItem>
          <SelectItem value="partial">
            In Progress{formatCount(counts?.progress.partial)}
          </SelectItem>
          <SelectItem value="100">
            Complete{formatCount(counts?.progress["100"])}
          </SelectItem>
        </SelectContent>
      </Select>

      {/* Status Filter - Dropdown */}
      <Select
        value={statusFilter}
        onValueChange={(value) => onStatusChange(value as StatusFilter)}
      >
        <SelectTrigger className="w-[130px] h-9">
          <SelectValue placeholder="Status" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All Status</SelectItem>
          <SelectItem value="Active">
            Active{formatCount(counts?.status.Active)}
          </SelectItem>
          <SelectItem value="Paused">
            Paused{formatCount(counts?.status.Paused)}
          </SelectItem>
          <SelectItem value="Ended">
            Ended{formatCount(counts?.status.Ended)}
          </SelectItem>
        </SelectContent>
      </Select>

      {/* Active Filters Indicator */}
      {(progressFilter !== "all" || statusFilter !== "all") && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            onProgressChange("all");
            onStatusChange("all");
          }}
          className="h-8 px-2 text-xs text-muted-foreground hover:text-foreground"
        >
          Clear filters
        </Button>
      )}
    </div>
  );
}
