import type { ReactElement } from "react";
import { Check } from "lucide-react";
import StatusBadge from "@/components/StatusBadge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import type { SettableIssueStatus } from "@/types";

const SETTABLE_ISSUE_STATUSES: SettableIssueStatus[] = [
  "Wanted",
  "Skipped",
  "Ignored",
  "Archived",
];

interface IssueStatusMenuProps {
  /** Current display state; matching option is checked. Omit for bulk use. */
  current?: string | null;
  onSelect: (status: SettableIssueStatus) => void;
  disabled?: boolean;
  /** Accessible name for the default badge trigger. */
  label?: string;
  /** Custom trigger element (Base UI `render`); defaults to a clickable badge. */
  trigger?: ReactElement;
}

/**
 * Status picker for one issue/annual or a selection. The default trigger makes
 * the StatusBadge itself the menu affordance; a `trigger` renders it elsewhere
 * (e.g. a bulk action bar).
 */
export default function IssueStatusMenu({
  current,
  onSelect,
  disabled,
  label,
  trigger,
}: IssueStatusMenuProps) {
  const normalized = current?.toLowerCase();
  return (
    <DropdownMenu>
      {trigger ? (
        <DropdownMenuTrigger render={trigger} disabled={disabled} />
      ) : (
        <DropdownMenuTrigger
          disabled={disabled}
          aria-label={label ?? "Change status"}
          title="Change status"
          className="cursor-pointer rounded-full outline-none transition-shadow focus-visible:ring-1 focus-visible:ring-ring data-disabled:cursor-not-allowed data-disabled:opacity-60"
        >
          <StatusBadge status={current} />
        </DropdownMenuTrigger>
      )}
      <DropdownMenuContent align="start" sideOffset={4}>
        <DropdownMenuGroup>
          <DropdownMenuLabel className="font-mono text-[10px] uppercase tracking-[0.08em]">
            Set status
          </DropdownMenuLabel>
          {SETTABLE_ISSUE_STATUSES.map((option) => (
            <DropdownMenuItem key={option} onClick={() => onSelect(option)}>
              <Check
                className={cn(
                  "h-3.5 w-3.5",
                  option.toLowerCase() !== normalized && "invisible",
                )}
                aria-hidden="true"
              />
              {option}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
