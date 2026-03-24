import { useState } from "react";
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
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useSetArcIssueStatus, useDelArcIssue } from "@/hooks/useStoryArcs";
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

export default function ArcIssueTable({
  issues,
  storyArcId,
}: ArcIssueTableProps) {
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const { addToast } = useToast();

  const setStatusMutation = useSetArcIssueStatus(storyArcId);
  const delIssueMutation = useDelArcIssue();

  const handleStatusChange = (issueArcId: string, status: ArcIssueStatus) => {
    setOpenMenuId(null);
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
    setOpenMenuId(null);
    setConfirmDeleteId(null);
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

  return (
    <div className="rounded-lg border border-card-border bg-card overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-card-border bg-muted/50">
            <th className="text-left px-4 py-3 font-medium text-muted-foreground w-12">
              #
            </th>
            <th className="text-left px-4 py-3 font-medium text-muted-foreground">
              Issue
            </th>
            <th className="text-left px-4 py-3 font-medium text-muted-foreground hidden md:table-cell">
              Date
            </th>
            <th className="text-left px-4 py-3 font-medium text-muted-foreground w-28">
              Status
            </th>
            <th className="text-right px-4 py-3 font-medium text-muted-foreground w-12" />
          </tr>
        </thead>
        <tbody>
          {issues.map((issue) => (
            <tr
              key={issue.IssueArcID}
              className="border-b border-card-border last:border-0 hover:bg-muted/30 transition-colors"
            >
              <td className="px-4 py-3 text-muted-foreground tabular-nums">
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
                  <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                    {issue.IssueName}
                  </p>
                )}
              </td>
              <td className="px-4 py-3 text-muted-foreground hidden md:table-cell">
                {issue.IssueDate || "-"}
              </td>
              <td className="px-4 py-3">
                <Badge variant={STATUS_BADGE_MAP[issue.Status] || "default"}>
                  {issue.Status}
                </Badge>
              </td>
              <td className="px-4 py-3 text-right">
                <div className="relative">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 w-8 p-0"
                    aria-haspopup="true"
                    aria-expanded={openMenuId === issue.IssueArcID}
                    aria-label={`Actions for ${issue.ComicName} #${issue.IssueNumber}`}
                    onClick={() =>
                      setOpenMenuId(
                        openMenuId === issue.IssueArcID
                          ? null
                          : issue.IssueArcID,
                      )
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Escape") setOpenMenuId(null);
                    }}
                  >
                    <MoreHorizontal className="w-4 h-4" />
                  </Button>

                  {openMenuId === issue.IssueArcID && (
                    <>
                      {/* Click-away backdrop */}
                      <div
                        className="fixed inset-0 z-40"
                        onClick={() => {
                          setOpenMenuId(null);
                          setConfirmDeleteId(null);
                        }}
                      />
                      <div
                        role="menu"
                        className="absolute right-0 top-full mt-1 z-50 min-w-[10rem] rounded-md border border-card-border bg-card shadow-lg p-1"
                      >
                        {issue.Status === "Read" ? (
                          <button
                            className="flex items-center gap-2 w-full px-3 py-1.5 text-sm rounded-sm hover:bg-muted transition-colors text-left"
                            onClick={() =>
                              handleStatusChange(issue.IssueArcID, "Wanted")
                            }
                          >
                            <EyeOff className="w-4 h-4" />
                            Mark as Unread
                          </button>
                        ) : (
                          <button
                            className="flex items-center gap-2 w-full px-3 py-1.5 text-sm rounded-sm hover:bg-muted transition-colors text-left"
                            onClick={() =>
                              handleStatusChange(issue.IssueArcID, "Read")
                            }
                          >
                            <Eye className="w-4 h-4" />
                            Mark as Read
                          </button>
                        )}
                        {issue.Status !== "Wanted" &&
                          issue.Status !== "Read" && (
                            <button
                              className="flex items-center gap-2 w-full px-3 py-1.5 text-sm rounded-sm hover:bg-muted transition-colors text-left"
                              onClick={() =>
                                handleStatusChange(issue.IssueArcID, "Wanted")
                              }
                            >
                              <Search className="w-4 h-4" />
                              Mark as Wanted
                            </button>
                          )}
                        <button
                          className="flex items-center gap-2 w-full px-3 py-1.5 text-sm rounded-sm hover:bg-muted transition-colors text-left"
                          onClick={() =>
                            handleStatusChange(issue.IssueArcID, "Skipped")
                          }
                        >
                          <BookOpen className="w-4 h-4" />
                          Mark as Skipped
                        </button>

                        {issue.ComicID && (
                          <>
                            <div className="my-1 border-t border-card-border" />
                            <Link
                              to={`/series/${issue.ComicID}`}
                              className="flex items-center gap-2 w-full px-3 py-1.5 text-sm rounded-sm hover:bg-muted transition-colors text-left"
                              onClick={() => setOpenMenuId(null)}
                            >
                              <ExternalLink className="w-4 h-4" />
                              View in Series
                            </Link>
                          </>
                        )}

                        <div className="my-1 border-t border-card-border" />
                        {confirmDeleteId === issue.IssueArcID ? (
                          <div className="flex items-center gap-1 px-1 py-1">
                            <button
                              className="flex-1 px-2 py-1 text-xs rounded bg-red-600 text-white hover:bg-red-700"
                              onClick={() => handleRemove(issue.IssueArcID)}
                            >
                              Confirm
                            </button>
                            <button
                              className="flex-1 px-2 py-1 text-xs rounded hover:bg-muted"
                              onClick={() => setConfirmDeleteId(null)}
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <button
                            className="flex items-center gap-2 w-full px-3 py-1.5 text-sm rounded-sm hover:bg-red-500/10 text-red-600 transition-colors text-left"
                            onClick={() => setConfirmDeleteId(issue.IssueArcID)}
                          >
                            <Trash2 className="w-4 h-4" />
                            Remove from Arc
                          </button>
                        )}
                      </div>
                    </>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
