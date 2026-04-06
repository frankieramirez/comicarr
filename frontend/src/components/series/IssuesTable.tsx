import { useState, useMemo, useCallback } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getExpandedRowModel,
  createColumnHelper,
  type SortingState,
  type RowSelectionState,
  type ExpandedState,
} from "@tanstack/react-table";
import {
  Download,
  X,
  Search,
  Filter,
  List,
  Layers,
  ChevronRight,
  Tags,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import StatusBadge from "@/components/StatusBadge";
import EmptyState from "@/components/ui/EmptyState";
import { DataTable } from "@/components/data-table/DataTable";
import { DataTableSortHeader } from "@/components/data-table/DataTableSortHeader";
import { ProgressBarCell } from "@/components/data-table/cells/ProgressBarCell";
import { TableCell, TableRow } from "@/components/ui/table";
import { useQueueIssue, useUnqueueIssue } from "@/hooks/useSeries";
import { useBulkQueueIssues, useBulkUnqueueIssues } from "@/hooks/useQueue";
import { useBulkMetatag } from "@/hooks/useMetadata";
import { useToast } from "@/components/ui/toast";
import type { Issue, VolumeGroup } from "@/types";

const issueColumnHelper = createColumnHelper<Issue>();
const volumeColumnHelper = createColumnHelper<VolumeGroup>();

type StatusFilter = "all" | "wanted" | "downloaded" | "skipped" | "other";
type ViewMode = "chapters" | "volumes";

interface IssuesTableProps {
  issues?: Issue[];
  isManga?: boolean;
  comicId?: string;
}

function groupByVolume(issues: Issue[]): VolumeGroup[] {
  const volumeMap = new Map<string, Issue[]>();
  const noVolumeIssues: Issue[] = [];

  issues.forEach((issue) => {
    const volumeNum = issue.volumeNumber;
    if (volumeNum) {
      const existing = volumeMap.get(volumeNum) || [];
      existing.push(issue);
      volumeMap.set(volumeNum, existing);
    } else {
      noVolumeIssues.push(issue);
    }
  });

  const volumes: VolumeGroup[] = [];

  const sortedVolumes = Array.from(volumeMap.entries()).sort((a, b) => {
    const numA = parseFloat(a[0]) || 0;
    const numB = parseFloat(b[0]) || 0;
    return numA - numB;
  });

  sortedVolumes.forEach(([volumeNum, chapters]) => {
    const downloadedCount = chapters.filter(
      (ch) => (ch.status ?? ch.Status)?.toLowerCase() === "downloaded",
    ).length;
    const totalCount = chapters.length;

    let status: VolumeGroup["status"] = "Missing";
    if (downloadedCount === totalCount) status = "Complete";
    else if (downloadedCount > 0) status = "Partial";

    volumes.push({
      volume: volumeNum,
      chapters: chapters.sort((a, b) => {
        const numA = parseFloat(a.chapterNumber || a.number || "0") || 0;
        const numB = parseFloat(b.chapterNumber || b.number || "0") || 0;
        return numA - numB;
      }),
      status,
      downloadedCount,
      totalCount,
    });
  });

  if (noVolumeIssues.length > 0) {
    const downloadedCount = noVolumeIssues.filter(
      (ch) => (ch.status ?? ch.Status)?.toLowerCase() === "downloaded",
    ).length;

    volumes.push({
      volume: "No Volume",
      chapters: noVolumeIssues.sort((a, b) => {
        const numA = parseFloat(a.chapterNumber || a.number || "0") || 0;
        const numB = parseFloat(b.chapterNumber || b.number || "0") || 0;
        return numA - numB;
      }),
      status:
        downloadedCount === noVolumeIssues.length
          ? "Complete"
          : downloadedCount > 0
            ? "Partial"
            : "Missing",
      downloadedCount,
      totalCount: noVolumeIssues.length,
    });
  }

  return volumes;
}

function getChapterRange(chapters: Issue[]): string {
  if (chapters.length === 0) return "\u2014";
  if (chapters.length === 1) {
    return `Ch. ${chapters[0].chapterNumber || chapters[0].number || "?"}`;
  }

  const numbers = chapters
    .map((ch) => ch.chapterNumber || ch.number)
    .filter(Boolean);

  if (numbers.length === 0) return "\u2014";
  return `Ch. ${numbers[0]}\u2013${numbers[numbers.length - 1]}`;
}

export default function IssuesTable({
  issues = [],
  isManga = false,
  comicId,
}: IssuesTableProps) {
  const itemLabel = isManga ? "chapter" : "issue";
  const itemLabelPlural = isManga ? "chapters" : "issues";
  const itemLabelCapitalized = isManga ? "Chapter" : "Issue";

  const [sorting, setSorting] = useState<SortingState>([
    { id: "number", desc: false },
  ]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [viewMode, setViewMode] = useState<ViewMode>("chapters");
  const [expanded, setExpanded] = useState<ExpandedState>({});

  const queueIssueMutation = useQueueIssue();
  const unqueueIssueMutation = useUnqueueIssue();
  const bulkQueueMutation = useBulkQueueIssues();
  const bulkUnqueueMutation = useBulkUnqueueIssues();
  const bulkMetatagMutation = useBulkMetatag();
  const { addToast } = useToast();

  const hasVolumeData = useMemo(
    () => issues.some((issue) => issue.volumeNumber),
    [issues],
  );

  const volumeGroups = useMemo(() => {
    if (viewMode !== "volumes") return [];
    return groupByVolume(issues);
  }, [issues, viewMode]);

  const filteredByStatus = useMemo(() => {
    if (statusFilter === "all") return issues;
    return issues.filter((issue) => {
      const status = (issue.status ?? issue.Status)?.toLowerCase();
      if (statusFilter === "other") {
        return !["wanted", "downloaded", "skipped", "snatched"].includes(
          status || "",
        );
      }
      return status === statusFilter;
    });
  }, [issues, statusFilter]);

  const selectedIssueIds = useMemo(() => {
    return Object.keys(rowSelection)
      .map((index) => {
        const issue = filteredByStatus[parseInt(index)];
        return issue?.id ?? issue?.IssueID;
      })
      .filter(Boolean) as string[];
  }, [rowSelection, filteredByStatus]);

  const handleBulkWant = async () => {
    try {
      await bulkQueueMutation.mutateAsync(selectedIssueIds);
      addToast({
        type: "success",
        message: `${selectedIssueIds.length} ${selectedIssueIds.length !== 1 ? itemLabelPlural : itemLabel} marked as wanted`,
      });
      setRowSelection({});
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to mark ${itemLabelPlural}: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleBulkSkip = async () => {
    try {
      await bulkUnqueueMutation.mutateAsync(selectedIssueIds);
      addToast({
        type: "success",
        message: `${selectedIssueIds.length} ${selectedIssueIds.length !== 1 ? itemLabelPlural : itemLabel} skipped`,
      });
      setRowSelection({});
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to skip ${itemLabelPlural}: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleBulkMetatag = async () => {
    if (!comicId) {
      addToast({
        type: "error",
        message: "Cannot tag metadata: missing series ID",
      });
      return;
    }
    try {
      await bulkMetatagMutation.mutateAsync({
        comicId,
        issueIds: selectedIssueIds,
      });
      addToast({
        type: "success",
        message: `Tagging metadata for ${selectedIssueIds.length} ${selectedIssueIds.length !== 1 ? itemLabelPlural : itemLabel}`,
      });
      setRowSelection({});
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to tag metadata: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleWantAll = async () => {
    const allIds = filteredByStatus
      .map((issue) => issue.id ?? issue.IssueID)
      .filter(Boolean) as string[];
    try {
      await bulkQueueMutation.mutateAsync(allIds);
      addToast({
        type: "success",
        message: `${allIds.length} ${itemLabelPlural} marked as wanted`,
      });
    } catch (err) {
      addToast({
        type: "error",
        message: `Failed to mark ${itemLabelPlural}: ${err instanceof Error ? err.message : "Unknown error"}`,
      });
    }
  };

  const handleWantVolume = useCallback(
    async (volume: VolumeGroup) => {
      const ids = volume.chapters
        .map((ch) => ch.id ?? ch.IssueID)
        .filter(Boolean) as string[];
      try {
        await bulkQueueMutation.mutateAsync(ids);
        addToast({
          type: "success",
          message: `${ids.length} chapters from Volume ${volume.volume} marked as wanted`,
        });
      } catch (err) {
        addToast({
          type: "error",
          message: `Failed to mark chapters: ${err instanceof Error ? err.message : "Unknown error"}`,
        });
      }
    },
    [bulkQueueMutation, addToast],
  );

  // Chapters view columns
  const chapterColumns = useMemo(
    () => [
      issueColumnHelper.display({
        id: "select",
        header: ({ table }) => (
          <Checkbox
            checked={
              table.getIsAllPageRowsSelected() ||
              (table.getIsSomePageRowsSelected() && "indeterminate")
            }
            onCheckedChange={(value) =>
              table.toggleAllPageRowsSelected(!!value)
            }
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            checked={row.getIsSelected()}
            onCheckedChange={(value) => row.toggleSelected(!!value)}
          />
        ),
        size: 40,
        enableSorting: false,
      }),
      issueColumnHelper.accessor("number", {
        header: ({ column }) => (
          <DataTableSortHeader column={column} title="#" />
        ),
        cell: ({ getValue }) => (
          <span className="font-mono text-sm">{getValue() || "N/A"}</span>
        ),
      }),
      ...(isManga && hasVolumeData
        ? [
            issueColumnHelper.accessor("volumeNumber", {
              id: "volume",
              header: "Vol",
              cell: ({ getValue }) => (
                <span className="font-mono text-sm text-muted-foreground">
                  {getValue() || "\u2014"}
                </span>
              ),
              enableSorting: false,
            }),
          ]
        : []),
      issueColumnHelper.accessor("name", {
        header: ({ column }) => (
          <DataTableSortHeader
            column={column}
            title={`${itemLabelCapitalized} Name`}
          />
        ),
        cell: ({ row }) => (
          <div>
            <div className="font-medium">{row.original.number}</div>
            {row.original.name && (
              <div className="text-sm text-muted-foreground">
                {row.original.name}
              </div>
            )}
          </div>
        ),
      }),
      issueColumnHelper.accessor("releaseDate", {
        header: ({ column }) => (
          <DataTableSortHeader column={column} title="Release Date" />
        ),
        cell: ({ getValue }) => {
          const date = getValue();
          if (!date)
            return <span className="text-muted-foreground/70">N/A</span>;
          return <span className="text-sm">{date}</span>;
        },
      }),
      issueColumnHelper.accessor((row) => row.status ?? row.Status, {
        id: "status",
        header: "Status",
        cell: ({ row }) => (
          <StatusBadge status={row.original.status ?? row.original.Status} />
        ),
        enableSorting: false,
      }),
      issueColumnHelper.display({
        id: "actions",
        header: "Actions",
        cell: ({ row }) => {
          const status = (
            row.original.status ?? row.original.Status
          )?.toLowerCase();
          const issueId = row.original.id ?? row.original.IssueID;

          return (
            <div className="flex items-center space-x-2">
              {status === "wanted" && issueId && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={(e) => {
                    e.stopPropagation();
                    unqueueIssueMutation.mutate(issueId);
                  }}
                  disabled={unqueueIssueMutation.isPending}
                  className="text-xs"
                >
                  <X className="w-3 h-3 mr-1" />
                  Skip
                </Button>
              )}
              {status === "skipped" && issueId && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={(e) => {
                    e.stopPropagation();
                    queueIssueMutation.mutate(issueId);
                  }}
                  disabled={queueIssueMutation.isPending}
                  className="text-xs"
                >
                  <Download className="w-3 h-3 mr-1" />
                  Want
                </Button>
              )}
              {status !== "wanted" &&
                status !== "skipped" &&
                status !== "downloaded" &&
                status !== "snatched" &&
                issueId && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation();
                      queueIssueMutation.mutate(issueId);
                    }}
                    disabled={queueIssueMutation.isPending}
                    className="text-xs"
                  >
                    <Download className="w-3 h-3 mr-1" />
                    Want
                  </Button>
                )}
            </div>
          );
        },
      }),
    ],
    [
      isManga,
      hasVolumeData,
      itemLabelCapitalized,
      queueIssueMutation,
      unqueueIssueMutation,
    ],
  );

  // Volume view columns
  const volumeColumns = useMemo(
    () => [
      volumeColumnHelper.display({
        id: "expander",
        header: "",
        cell: ({ row }) => (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => row.toggleExpanded()}
            className="p-1 h-6 w-6"
          >
            <ChevronRight
              className={`w-4 h-4 transition-transform ${row.getIsExpanded() ? "rotate-90" : ""}`}
            />
          </Button>
        ),
        size: 40,
      }),
      volumeColumnHelper.accessor("volume", {
        header: "Volume",
        cell: ({ getValue }) => (
          <span className="font-medium">Vol. {getValue()}</span>
        ),
        enableSorting: false,
      }),
      volumeColumnHelper.display({
        id: "chapters",
        header: "Chapters",
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {getChapterRange(row.original.chapters)}
          </span>
        ),
      }),
      volumeColumnHelper.accessor("status", {
        header: "Status",
        cell: ({ row }) => (
          <Badge
            variant={
              row.original.status === "Complete"
                ? "default"
                : row.original.status === "Partial"
                  ? "secondary"
                  : "outline"
            }
          >
            {row.original.status}
          </Badge>
        ),
        enableSorting: false,
      }),
      volumeColumnHelper.display({
        id: "progress",
        header: "Progress",
        cell: ({ row }) => {
          const { downloadedCount, totalCount } = row.original;
          const percentage =
            totalCount > 0
              ? Math.round((downloadedCount / totalCount) * 100)
              : 0;
          return <ProgressBarCell percentage={percentage} />;
        },
      }),
      volumeColumnHelper.display({
        id: "actions",
        header: "",
        cell: ({ row }) => {
          const hasWantable = row.original.chapters.some((ch) => {
            const status = (ch.status ?? ch.Status)?.toLowerCase();
            return status !== "downloaded" && status !== "snatched";
          });
          if (!hasWantable) return null;
          return (
            <Button
              size="sm"
              variant="outline"
              onClick={() => handleWantVolume(row.original)}
              disabled={bulkQueueMutation.isPending}
              className="text-xs"
            >
              <Download className="w-3 h-3 mr-1" />
              Want All
            </Button>
          );
        },
      }),
    ],
    [bulkQueueMutation.isPending, handleWantVolume],
  );

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = { all: issues.length };
    issues.forEach((issue) => {
      const status = (issue.status ?? issue.Status)?.toLowerCase() || "other";
      counts[status] = (counts[status] || 0) + 1;
    });
    return counts;
  }, [issues]);

  const chaptersTable = useReactTable({
    data: filteredByStatus,
    columns: chapterColumns,
    state: { sorting, globalFilter, rowSelection },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    enableRowSelection: true,
    initialState: { pagination: { pageSize: 50 } },
  });

  const volumesTable = useReactTable({
    data: volumeGroups,
    columns: volumeColumns,
    state: { expanded },
    onExpandedChange: setExpanded,
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    getRowCanExpand: () => true,
  });

  if (issues.length === 0) {
    return <EmptyState variant="issues" />;
  }

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
        <div className="flex items-center gap-4 flex-1">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder={`Search ${itemLabelPlural} by number or name...`}
              value={globalFilter}
              onChange={(e) => setGlobalFilter(e.target.value)}
              className="pl-9"
            />
          </div>

          {isManga && hasVolumeData && (
            <div className="flex items-center gap-1 bg-muted rounded-lg p-1">
              <Button
                variant={viewMode === "chapters" ? "default" : "ghost"}
                size="sm"
                onClick={() => setViewMode("chapters")}
                className="h-7 text-xs"
              >
                <List className="w-3 h-3 mr-1" />
                Chapters
              </Button>
              <Button
                variant={viewMode === "volumes" ? "default" : "ghost"}
                size="sm"
                onClick={() => setViewMode("volumes")}
                className="h-7 text-xs"
              >
                <Layers className="w-3 h-3 mr-1" />
                Volumes
              </Button>
            </div>
          )}
        </div>

        {viewMode === "chapters" && (
          <div className="flex items-center gap-2 flex-wrap">
            <div className="flex items-center gap-1 bg-muted rounded-lg p-1">
              <Filter className="w-4 h-4 ml-2 text-muted-foreground" />
              {(
                [
                  ["all", "All"],
                  ["wanted", "Wanted"],
                  ["downloaded", "Downloaded"],
                  ["skipped", "Skipped"],
                ] as const
              ).map(([value, label]) => (
                <Button
                  key={value}
                  variant={statusFilter === value ? "default" : "ghost"}
                  size="sm"
                  onClick={() => setStatusFilter(value)}
                  className="h-7 text-xs"
                >
                  {label}
                  {statusCounts[value] !== undefined && (
                    <span className="ml-1 text-muted-foreground">
                      ({statusCounts[value]})
                    </span>
                  )}
                </Button>
              ))}
            </div>

            <Button
              variant="outline"
              size="sm"
              onClick={handleWantAll}
              disabled={
                bulkQueueMutation.isPending || filteredByStatus.length === 0
              }
            >
              <Download className="w-3 h-3 mr-1" />
              Want All
            </Button>
          </div>
        )}
      </div>

      {/* Bulk Action Bar (chapters view only) */}
      {viewMode === "chapters" && selectedIssueIds.length > 0 && (
        <div className="flex items-center gap-4 px-4 py-3 bg-primary/10 border border-primary/20 rounded-lg">
          <span className="text-sm font-medium">
            {selectedIssueIds.length}{" "}
            {selectedIssueIds.length !== 1 ? itemLabelPlural : itemLabel}{" "}
            selected
          </span>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={handleBulkWant}
              disabled={bulkQueueMutation.isPending}
            >
              <Download className="w-3 h-3 mr-1" />
              Mark Wanted
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={handleBulkSkip}
              disabled={bulkUnqueueMutation.isPending}
            >
              <X className="w-3 h-3 mr-1" />
              Skip
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={handleBulkMetatag}
              disabled={bulkMetatagMutation.isPending || !comicId}
            >
              <Tags className="w-3 h-3 mr-1" />
              Tag Metadata
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setRowSelection({})}
            >
              Clear
            </Button>
          </div>
        </div>
      )}

      {/* Table */}
      {viewMode === "chapters" ? (
        <>
          <DataTable table={chaptersTable} />
          <div className="flex items-center justify-between">
            <div className="text-sm text-muted-foreground">
              Showing{" "}
              {chaptersTable.getState().pagination.pageIndex *
                chaptersTable.getState().pagination.pageSize +
                1}{" "}
              to{" "}
              {Math.min(
                (chaptersTable.getState().pagination.pageIndex + 1) *
                  chaptersTable.getState().pagination.pageSize,
                chaptersTable.getFilteredRowModel().rows.length,
              )}{" "}
              of {chaptersTable.getFilteredRowModel().rows.length}{" "}
              {itemLabelPlural}
              {globalFilter && ` (filtered from ${filteredByStatus.length})`}
            </div>
            <div className="flex items-center space-x-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => chaptersTable.previousPage()}
                disabled={!chaptersTable.getCanPreviousPage()}
              >
                Previous
              </Button>
              <span className="text-sm text-muted-foreground">
                Page {chaptersTable.getState().pagination.pageIndex + 1} of{" "}
                {chaptersTable.getPageCount()}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => chaptersTable.nextPage()}
                disabled={!chaptersTable.getCanNextPage()}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      ) : (
        <>
          <DataTable
            table={volumesTable}
            onRowClick={(row) => {
              const tableRow = volumesTable
                .getRowModel()
                .rows.find((r) => r.original === row);
              tableRow?.toggleExpanded();
            }}
            renderSubRow={(row, colSpan) => (
              <TableRow key={`${row.id}-expanded`}>
                <TableCell colSpan={colSpan} className="p-0">
                  <div className="bg-muted/30 border-y border-card-border">
                    <table className="w-full">
                      <tbody>
                        {row.original.chapters.map((chapter) => {
                          const status = (
                            chapter.status ?? chapter.Status
                          )?.toLowerCase();
                          const issueId = chapter.id ?? chapter.IssueID;

                          return (
                            <tr key={issueId} className="hover:bg-accent/30">
                              <td className="pl-12 pr-6 py-2 w-10" />
                              <td className="px-6 py-2">
                                <span className="font-mono text-sm">
                                  Ch.{" "}
                                  {chapter.chapterNumber ||
                                    chapter.number ||
                                    "?"}
                                </span>
                              </td>
                              <td className="px-6 py-2">
                                <span className="text-sm text-muted-foreground">
                                  {chapter.name || "\u2014"}
                                </span>
                              </td>
                              <td className="px-6 py-2">
                                <StatusBadge
                                  status={chapter.status ?? chapter.Status}
                                />
                              </td>
                              <td className="px-6 py-2" />
                              <td className="px-6 py-2">
                                {status !== "downloaded" &&
                                  status !== "snatched" &&
                                  issueId && (
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        queueIssueMutation.mutate(issueId);
                                      }}
                                      disabled={queueIssueMutation.isPending}
                                      className="text-xs h-6"
                                    >
                                      <Download className="w-3 h-3 mr-1" />
                                      Want
                                    </Button>
                                  )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </TableCell>
              </TableRow>
            )}
          />
          <div className="text-sm text-muted-foreground">
            {volumeGroups.length} volumes \u2022 {issues.length} total{" "}
            {itemLabelPlural}
          </div>
        </>
      )}
    </div>
  );
}
