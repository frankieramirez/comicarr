import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import type { ReactElement } from "react";
import { Check } from "lucide-react";
import StatusBadge from "@/components/StatusBadge";
import { statusTone } from "@/lib/statusTone";
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

// API status values; the menu shows statusLabel() for each.
const WANTED = "Wanted";
const SKIPPED = "Skipped";
const IGNORED = "Ignored";
const ARCHIVED = "Archived";
const SETTABLE_ISSUE_STATUSES: SettableIssueStatus[] = [
  WANTED,
  SKIPPED,
  IGNORED,
  ARCHIVED,
];

function statusLabel(status: SettableIssueStatus): string {
  switch (status) {
    case "Wanted":
      return t`Wanted`;
    case "Skipped":
      return t`Skipped`;
    case "Ignored":
      return t`Ignored`;
    case "Archived":
      return t`Archived`;
  }
}

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
  // The name starts with the status the badge shows, so speech users can say
  // what they see (WCAG 2.5.3, #1499).
  const shown = statusTone(current)?.label;
  const action = label ?? t`Change status`;
  const name = shown ? t`${shown}, ${action}` : action;
  return (
    <DropdownMenu>
      {trigger ? (
        <DropdownMenuTrigger render={trigger} disabled={disabled} />
      ) : (
        <DropdownMenuTrigger
          disabled={disabled}
          aria-label={name}
          title={t`Change status`}
          className="cursor-pointer rounded-full outline-none transition-shadow focus-visible:ring-1 focus-visible:ring-ring data-disabled:cursor-not-allowed data-disabled:opacity-60"
        >
          <StatusBadge status={current} />
        </DropdownMenuTrigger>
      )}
      <DropdownMenuContent align="start" sideOffset={4}>
        <DropdownMenuGroup>
          <DropdownMenuLabel className="mono-label">
            <Trans>Set status</Trans>
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
              {statusLabel(option)}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
