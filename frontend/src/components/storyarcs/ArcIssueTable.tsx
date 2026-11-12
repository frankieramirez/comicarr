import { useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  MoreHorizontal,
  BookOpen,
  Eye,
  EyeOff,
  Search,
  Trash2,
  ExternalLink,
} from "lucide-react";
import { createColumnHelper } from "@tanstack/react-table";
import StatusBadge from "@/components/StatusBadge";
import { DataTable } from "@/components/data-table/DataTable";
import {
  type ComicarrTableFeatures,
  useTableState,
} from "@/components/data-table/useTableState";
import { buttonVariants } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useToast } from "@/components/ui/toast";
import { ReleaseReviewSheet } from "@/components/releases/ReleaseReviewSheet";
import { useInteractiveReview } from "@/hooks/useInteractiveSearch";
import { useSetArcIssueStatus, useDelArcIssue } from "@/hooks/useStoryArcs";
import { cn } from "@/lib/utils";
import type { ArcIssue, ArcIssueStatus } from "@/types";

interface ArcIssueTableProps {
  issues: ArcIssue[];
  storyArcId: string;
}

const columnHelper = createColumnHelper<ComicarrTableFeatures, ArcIssue>();

/** Read issues are held issues; the dot says so while the word stays "Read". */
function toneFor(status: ArcIssueStatus): string {
  return status === "Read" ? "Downloaded" : status;
}

function ArcIssueRowMenu({
  issue,
  onStatusChange,
  onRemove,
  onInteractiveSearch,
}: {
  issue: ArcIssue;
  onStatusChange: (issueArcId: string, status: ArcIssueStatus) => void;
  onRemove: (issueArcId: string) => void;
  onInteractiveSearch: (issue: ArcIssue) => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const confirmRef = useRef<HTMLDivElement>(null);
  const triggerLabel = `Actions for ${issue.ComicName} #${issue.IssueNumber}`;

  useLayoutEffect(() => {
    if (confirmDelete) confirmRef.current?.focus();
  }, [confirmDelete]);

  return (
    <DropdownMenu
      onOpenChange={(open) => {
        if (!open) setConfirmDelete(false);
      }}
    >
      <DropdownMenuTrigger
        aria-label={triggerLabel}
        className={cn(
          buttonVariants({ variant: "ghost", size: "icon-sm" }),
          "opacity-60 transition-opacity group-hover/row:opacity-100 focus-visible:opacity-100 data-popup-open:opacity-100",
        )}
      >
        <MoreHorizontal className="h-4 w-4" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[10rem]">
        <DropdownMenuItem onClick={() => onInteractiveSearch(issue)}>
          <Search className="h-4 w-4" />
          Interactive Search
        </DropdownMenuItem>
        {issue.Status === "Read" ? (
          <DropdownMenuItem
            onClick={() => onStatusChange(issue.IssueArcID, "Wanted")}
          >
            <EyeOff className="h-4 w-4" />
            Mark as Unread
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem
            onClick={() => onStatusChange(issue.IssueArcID, "Read")}
          >
            <Eye className="h-4 w-4" />
            Mark as Read
          </DropdownMenuItem>
        )}
        {issue.Status !== "Wanted" && issue.Status !== "Read" && (
          <DropdownMenuItem
            onClick={() => onStatusChange(issue.IssueArcID, "Wanted")}
          >
            <Search className="h-4 w-4" />
            Mark as Wanted
          </DropdownMenuItem>
        )}
        <DropdownMenuItem
          onClick={() => onStatusChange(issue.IssueArcID, "Skipped")}
        >
          <BookOpen className="h-4 w-4" />
          Mark as Skipped
        </DropdownMenuItem>

        {issue.ComicID && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              render={<Link to={`/library/${issue.ComicID}`} />}
            >
              <ExternalLink className="h-4 w-4" />
              View in Library
            </DropdownMenuItem>
          </>
        )}

        <DropdownMenuSeparator />
        {confirmDelete ? (
          <>
            <DropdownMenuItem
              ref={confirmRef}
              className="text-destructive focus:text-destructive"
              onClick={() => onRemove(issue.IssueArcID)}
            >
              Confirm
            </DropdownMenuItem>
            <DropdownMenuItem
              closeOnClick={false}
              onClick={() => setConfirmDelete(false)}
            >
              Cancel
            </DropdownMenuItem>
          </>
        ) : (
          <DropdownMenuItem
            closeOnClick={false}
            className="text-destructive focus:text-destructive"
            onClick={() => setConfirmDelete(true)}
          >
            <Trash2 className="h-4 w-4" />
            Remove from Arc
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export default function ArcIssueTable({
  issues,
  storyArcId,
}: ArcIssueTableProps) {
  const { addToast } = useToast();
  const { startReview, reviewSheetProps } = useInteractiveReview();

  const setStatusMutation = useSetArcIssueStatus(storyArcId);
  const delIssueMutation = useDelArcIssue();

  const handleStatusChange = (issueArcId: string, status: ArcIssueStatus) => {
    setStatusMutation.mutate(
      { issueArcId, status },
      {
        onError: () => {
          addToast({
            type: "error",
            title: "Error",
            description: "Failed to update status.",
          });
        },
      },
    );
  };

  const handleRemove = (issueArcId: string) => {
    delIssueMutation.mutate(
      { issueArcId, storyArcId },
      {
        onSuccess: () => {
          addToast({
            type: "success",
            title: "Removed",
            description: "Issue removed from arc.",
          });
        },
        onError: () => {
          addToast({
            type: "error",
            title: "Error",
            description: "Failed to remove issue.",
          });
        },
      },
    );
  };

  const handleInteractiveSearch = (issue: ArcIssue) => {
    void startReview(
      {
        IssueNumber: issue.IssueNumber,
        ComicName: issue.ComicName,
        Status: issue.Status,
      },
      {
        entityType: "story_arc_issue",
        entityId: issue.IssueArcID,
      },
    );
  };

  // Rebuilt each render so the row menus see the current handlers; the
  // menu element type is stable, so rows re-render rather than remount.
  const columns = columnHelper.columns([
    columnHelper.accessor("ReadingOrder", {
      header: "#",
      cell: ({ getValue }) => (
        <span className="font-mono text-xs text-muted-foreground">
          {getValue()}
        </span>
      ),
      size: 48,
    }),
    columnHelper.display({
      id: "issue",
      header: "Issue",
      cell: ({ row }) => {
        const issue = row.original;
        const label = (
          <>
            <span className="font-medium text-foreground">
              {issue.ComicName}
            </span>
            <span className="font-mono text-xs text-foreground-2">
              {" "}
              #{issue.IssueNumber}
            </span>
          </>
        );
        return (
          <div className="min-w-0 py-0.5 text-[13px]">
            {issue.ComicID && issue.IssueID ? (
              <Link
                to={`/library/${issue.ComicID}/issue/${issue.IssueID}`}
                className="hover:underline"
              >
                {label}
              </Link>
            ) : (
              label
            )}
            {issue.IssueName && (
              <p className="line-clamp-1 text-xs text-foreground-2">
                {issue.IssueName}
              </p>
            )}
          </div>
        );
      },
    }),
    columnHelper.accessor("IssueDate", {
      header: "Date",
      cell: ({ getValue }) => (
        <span className="mono-meta">{getValue() || "—"}</span>
      ),
      size: 120,
    }),
    columnHelper.accessor("Status", {
      header: "Status",
      cell: ({ getValue }) => (
        <StatusBadge
          variant="dot"
          status={toneFor(getValue())}
          label={getValue()}
        />
      ),
      size: 128,
    }),
    columnHelper.display({
      id: "actions",
      header: () => <span className="sr-only">Actions</span>,
      cell: ({ row }) => (
        <div className="flex justify-end">
          <ArcIssueRowMenu
            issue={row.original}
            onStatusChange={handleStatusChange}
            onRemove={handleRemove}
            onInteractiveSearch={handleInteractiveSearch}
          />
        </div>
      ),
      size: 48,
    }),
  ]);

  const { table } = useTableState({
    data: issues,
    columns,
    getRowId: (row) => row.IssueArcID,
  });

  return (
    <>
      <DataTable table={table} />
      <ReleaseReviewSheet {...reviewSheetProps} />
    </>
  );
}
