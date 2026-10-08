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
import { Badge } from "@/components/ui/badge";
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

const STATUS_BADGE_MAP: Record<
  ArcIssueStatus,
  "downloaded" | "wanted" | "skipped" | "default"
> = {
  Downloaded: "downloaded",
  Archived: "downloaded",
  Wanted: "wanted",
  Skipped: "skipped",
  Read: "default",
  Added: "default",
};

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
          buttonVariants({ variant: "ghost", size: "sm" }),
          "h-8 w-8 p-0",
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

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/50">
            <th className="w-12 px-4 py-3 text-left font-medium text-muted-foreground">
              #
            </th>
            <th className="px-4 py-3 text-left font-medium text-muted-foreground">
              Issue
            </th>
            <th className="hidden px-4 py-3 text-left font-medium text-muted-foreground md:table-cell">
              Date
            </th>
            <th className="w-28 px-4 py-3 text-left font-medium text-muted-foreground">
              Status
            </th>
            <th className="w-12 px-4 py-3 text-right font-medium text-muted-foreground" />
          </tr>
        </thead>
        <tbody>
          {issues.map((issue) => (
            <tr
              key={issue.IssueArcID}
              className="border-b border-border transition-colors last:border-0 hover:bg-muted/30"
            >
              <td className="px-4 py-3 tabular-nums text-muted-foreground">
                {issue.ReadingOrder}
              </td>
              <td className="px-4 py-3">
                <div>
                  <span className="font-medium text-foreground">
                    {issue.ComicName}
                  </span>
                  <span className="text-muted-foreground">
                    {" "}
                    #{issue.IssueNumber}
                  </span>
                </div>
                {issue.IssueName && (
                  <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                    {issue.IssueName}
                  </p>
                )}
              </td>
              <td className="hidden px-4 py-3 text-muted-foreground md:table-cell">
                {issue.IssueDate || "-"}
              </td>
              <td className="px-4 py-3">
                <Badge variant={STATUS_BADGE_MAP[issue.Status] || "default"}>
                  {issue.Status}
                </Badge>
              </td>
              <td className="px-4 py-3 text-right">
                <ArcIssueRowMenu
                  issue={issue}
                  onStatusChange={handleStatusChange}
                  onRemove={handleRemove}
                  onInteractiveSearch={handleInteractiveSearch}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ReleaseReviewSheet {...reviewSheetProps} />
    </div>
  );
}
