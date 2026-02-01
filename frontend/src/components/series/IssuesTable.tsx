import React, { useState, useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getExpandedRowModel,
  flexRender,
  ColumnDef,
  SortingState,
  RowSelectionState,
  ExpandedState,
  CellContext,
  HeaderContext,
} from "@tanstack/react-table";
import {
  Download,
  X,
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
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
import { useQueueIssue, useUnqueueIssue } from "@/hooks/useSeries";
import { useBulkQueueIssues, useBulkUnqueueIssues } from "@/hooks/useQueue";
import { useBulkMetatag } from "@/hooks/useMetadata";
import { useToast } from "@/components/ui/toast";
import type { Issue, VolumeGroup } from "@/types";

type StatusFilter = "all" | "wanted" | "downloaded" | "skipped" | "other";
type ViewMode = "chapters" | "volumes";

interface IssuesTableProps {
  issues?: Issue[];
  isManga?: boolean;
  comicId?: string;
}

// Helper to group issues by volume
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

  // Sort volumes numerically
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
    if (downloadedCount === totalCount) {
      status = "Complete";
    } else if (downloadedCount > 0) {
      status = "Partial";
    }

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

  // Add issues without volume at the end
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

// Get chapter range string for a volume
function getChapterRange(chapters: Issue[]): string {
  if (chapters.length === 0) return "—";
  if (chapters.length === 1) {
    return `Ch. ${chapters[0].chapterNumber || chapters[0].number || "?"}`;
  }

  const numbers = chapters
    .map((ch) => ch.chapterNumber || ch.number)
    .filter(Boolean);

  if (numbers.length === 0) return "—";

  const first = numbers[0];
  const last = numbers[numbers.length - 1];

  return `Ch. ${first}–${last}`;
}

export default function IssuesTable({
  issues = [],
  isManga = false,
  comicId,
}: IssuesTableProps) {
  // Dynamic labels based on content type
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

  // Check if any issues have volume numbers (determines if volume view is available)
  const hasVolumeData = useMemo(() => {
    return issues.some((issue) => issue.volumeNumber);
  }, [issues]);

  // Group issues by volume for volume view
  const volumeGroups = useMemo(() => {
    if (viewMode !== "volumes") return [];
    return groupByVolume(issues);
  }, [issues, viewMode]);

  // Filter issues by status
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

  const handleQueueIssue = (e: React.MouseEvent, issueId: string) => {
    e.stopPropagation();
    queueIssueMutation.mutate(issueId);
  };

  const handleUnqueueIssue = (e: React.MouseEvent, issueId: string) => {
    e.stopPropagation();
    unqueueIssueMutation.mutate(issueId);
  };

  // Bulk actions
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

  const handleWantVolume = async (volume: VolumeGroup) => {
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
  };

  // Chapters view columns
  const chapterColumns: ColumnDef<Issue>[] = useMemo(
    () => [
      {
        id: "select",
        header: ({ table }: HeaderContext<Issue, unknown>) => (
          <Checkbox
            checked={table.getIsAllPageRowsSelected()}
            indeterminate={
              table.getIsSomePageRowsSelected() &&
              !table.getIsAllPageRowsSelected()
            }
            onChange={table.getToggleAllPageRowsSelectedHandler()}
          />
        ),
        cell: ({ row }: CellContext<Issue, unknown>) => (
          <Checkbox
            checked={row.getIsSelected()}
            onChange={row.getToggleSelectedHandler()}
          />
        ),
        size: 40,
        enableSorting: false,
      },
      {
        accessorKey: "number",
        header: "#",
        cell: ({ getValue }: CellContext<Issue, unknown>) => (
          <span className="font-mono text-sm">
            {(getValue() as string) || "N/A"}
          </span>
        ),
      },
      // Show volume column if manga has volume data
      ...(isManga && hasVolumeData
        ? [
            {
              id: "volume",
              accessorKey: "volumeNumber",
              header: "Vol",
              cell: ({ row }: CellContext<Issue, unknown>) => (
                <span className="font-mono text-sm text-muted-foreground">
                  {row.original.volumeNumber || "—"}
                </span>
              ),
            },
          ]
        : []),
      {
        accessorKey: "name",
        header: `${itemLabelCapitalized} Name`,
        cell: ({ row }: CellContext<Issue, unknown>) => (
          <div>
            <div className="font-medium">{row.original.number}</div>
            {row.original.name && (
              <div className="text-sm text-muted-foreground">
                {row.original.name}
              </div>
            )}
          </div>
        ),
      },
      {
        accessorKey: "releaseDate",
        header: "Release Date",
        cell: ({ getValue }: CellContext<Issue, unknown>) => {
          const date = getValue() as string | undefined;
          if (!date)
            return <span className="text-muted-foreground/70">N/A</span>;
          return <span className="text-sm">{date}</span>;
        },
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }: CellContext<Issue, unknown>) => (
          <StatusBadge status={row.original.status ?? row.original.Status} />
        ),
      },
      {
        id: "actions",
        header: "Actions",
        cell: ({ row }: CellContext<Issue, unknown>) => {
          const status = (
            row.original.status ?? row.original.Status
          )?.toLowerCase();
          const issueId = row.original.id ?? row.original.IssueID;

          return (
            <div className="flex items-center space-x-2">
              {status === "wanted" || status === "skipped" ? (
                <>
                  {status === "wanted" && issueId && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={(e) => handleUnqueueIssue(e, issueId)}
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
                      onClick={(e) => handleQueueIssue(e, issueId)}
                      disabled={queueIssueMutation.isPending}
                      className="text-xs"
                    >
                      <Download className="w-3 h-3 mr-1" />
                      Want
                    </Button>
                  )}
                </>
              ) : status !== "downloaded" &&
                status !== "snatched" &&
                issueId ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={(e) => handleQueueIssue(e, issueId)}
                  disabled={queueIssueMutation.isPending}
                  className="text-xs"
                >
                  <Download className="w-3 h-3 mr-1" />
                  Want
                </Button>
              ) : null}
            </div>
          );
        },
      },
    ],
    [
      isManga,
      hasVolumeData,
      itemLabelCapitalized,
      queueIssueMutation.isPending,
      unqueueIssueMutation.isPending,
      handleQueueIssue,
      handleUnqueueIssue,
    ],
  );

  // Volume view columns
  const volumeColumns: ColumnDef<VolumeGroup>[] = useMemo(
    () => [
      {
        id: "expander",
        header: "",
        cell: ({ row }: CellContext<VolumeGroup, unknown>) => (
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
      },
      {
        accessorKey: "volume",
        header: "Volume",
        cell: ({ getValue }: CellContext<VolumeGroup, unknown>) => (
          <span className="font-medium">Vol. {getValue() as string}</span>
        ),
      },
      {
        id: "chapters",
        header: "Chapters",
        cell: ({ row }: CellContext<VolumeGroup, unknown>) => (
          <span className="text-sm text-muted-foreground">
            {getChapterRange(row.original.chapters)}
          </span>
        ),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }: CellContext<VolumeGroup, unknown>) => {
          const { status } = row.original;
          return (
            <Badge
              variant={
                status === "Complete"
                  ? "default"
                  : status === "Partial"
                    ? "secondary"
                    : "outline"
              }
            >
              {status}
            </Badge>
          );
        },
      },
      {
        id: "progress",
        header: "Progress",
        cell: ({ row }: CellContext<VolumeGroup, unknown>) => {
          const { downloadedCount, totalCount } = row.original;
          const percentage =
            totalCount > 0
              ? Math.round((downloadedCount / totalCount) * 100)
              : 0;

          return (
            <div className="flex items-center space-x-2">
              <div className="flex-1 bg-muted rounded-full h-2 overflow-hidden min-w-[60px]">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${percentage}%`,
                    background: "var(--gradient-brand)",
                  }}
                />
              </div>
              <span className="text-xs text-muted-foreground min-w-[4rem]">
                {downloadedCount}/{totalCount}
              </span>
            </div>
          );
        },
      },
      {
        id: "actions",
        header: "",
        cell: ({ row }: CellContext<VolumeGroup, unknown>) => {
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
      },
    ],
    [bulkQueueMutation.isPending, handleWantVolume],
  );

  // Status counts for filter badges
  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = { all: issues.length };
    issues.forEach((issue) => {
      const status = (issue.status ?? issue.Status)?.toLowerCase() || "other";
      counts[status] = (counts[status] || 0) + 1;
    });
    return counts;
  }, [issues]);

  // Chapters table
  const chaptersTable = useReactTable({
    data: filteredByStatus,
    columns: chapterColumns,
    state: {
      sorting,
      globalFilter,
      rowSelection,
    },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    enableRowSelection: true,
    initialState: {
      pagination: {
        pageSize: 50,
      },
    },
  });

  // Volumes table
  const volumesTable = useReactTable({
    data: volumeGroups,
    columns: volumeColumns,
    state: {
      expanded,
    },
    onExpandedChange: setExpanded,
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    getRowCanExpand: () => true,
  });

  if (issues.length === 0) {
    return <EmptyState variant="issues" />;
  }

  // Render expanded chapter rows for volume view
  const renderExpandedChapters = (volume: VolumeGroup) => (
    <tr>
      <td colSpan={volumeColumns.length} className="p-0">
        <div className="bg-muted/30 border-y border-card-border">
          <table className="w-full">
            <tbody>
              {volume.chapters.map((chapter) => {
                const status = (
                  chapter.status ?? chapter.Status
                )?.toLowerCase();
                const issueId = chapter.id ?? chapter.IssueID;

                return (
                  <tr key={issueId} className="hover:bg-accent/30">
                    <td className="pl-12 pr-6 py-2 w-10"></td>
                    <td className="px-6 py-2">
                      <span className="font-mono text-sm">
                        Ch. {chapter.chapterNumber || chapter.number || "?"}
                      </span>
                    </td>
                    <td className="px-6 py-2">
                      <span className="text-sm text-muted-foreground">
                        {chapter.name || "—"}
                      </span>
                    </td>
                    <td className="px-6 py-2">
                      <StatusBadge status={chapter.status ?? chapter.Status} />
                    </td>
                    <td className="px-6 py-2"></td>
                    <td className="px-6 py-2">
                      {status !== "downloaded" &&
                        status !== "snatched" &&
                        issueId && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={(e) => handleQueueIssue(e, issueId)}
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
      </td>
    </tr>
  );

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
        {/* Search & View Toggle */}
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

          {/* View Toggle - only show if manga has volume data */}
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

        {/* Status Filter & Quick Actions */}
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
      <div className="rounded-lg border border-card-border bg-card card-shadow overflow-hidden">
        <div className="overflow-x-auto custom-scrollbar">
          {viewMode === "chapters" ? (
            // Chapters View
            <table className="w-full">
              <thead className="bg-muted/50 border-card-border backdrop-blur-sm border-b">
                {chaptersTable.getHeaderGroups().map((headerGroup) => (
                  <tr key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <th
                        key={header.id}
                        className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider"
                      >
                        {header.isPlaceholder ? null : (
                          <div
                            className={
                              header.column.getCanSort()
                                ? "flex items-center space-x-1 cursor-pointer select-none hover:text-foreground"
                                : ""
                            }
                            onClick={header.column.getToggleSortingHandler()}
                          >
                            <span>
                              {flexRender(
                                header.column.columnDef.header,
                                header.getContext(),
                              )}
                            </span>
                            {header.column.getCanSort() && (
                              <span className="text-muted-foreground">
                                {header.column.getIsSorted() === "asc" ? (
                                  <ChevronUp className="w-4 h-4" />
                                ) : header.column.getIsSorted() === "desc" ? (
                                  <ChevronDown className="w-4 h-4" />
                                ) : (
                                  <ChevronsUpDown className="w-4 h-4 opacity-50" />
                                )}
                              </span>
                            )}
                          </div>
                        )}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody className="bg-card divide-y divide-card-border">
                {chaptersTable.getRowModel().rows.map((row) => (
                  <tr
                    key={row.id}
                    className={`hover:bg-accent/50 transition-colors ${
                      row.getIsSelected() ? "bg-primary/5" : ""
                    }`}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-6 py-4 whitespace-nowrap">
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext(),
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            // Volumes View
            <table className="w-full">
              <thead className="bg-muted/50 border-card-border backdrop-blur-sm border-b">
                {volumesTable.getHeaderGroups().map((headerGroup) => (
                  <tr key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <th
                        key={header.id}
                        className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider"
                      >
                        {header.isPlaceholder
                          ? null
                          : flexRender(
                              header.column.columnDef.header,
                              header.getContext(),
                            )}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody className="bg-card divide-y divide-card-border">
                {volumesTable.getRowModel().rows.map((row) => (
                  <React.Fragment key={row.id}>
                    <tr
                      className="hover:bg-accent/50 transition-colors cursor-pointer"
                      onClick={() => row.toggleExpanded()}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <td
                          key={cell.id}
                          className="px-6 py-4 whitespace-nowrap"
                        >
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext(),
                          )}
                        </td>
                      ))}
                    </tr>
                    {row.getIsExpanded() &&
                      renderExpandedChapters(row.original)}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination (chapters view only) */}
        {viewMode === "chapters" && (
          <div className="border-t border-card-border px-6 py-3 flex items-center justify-between bg-muted/50">
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
        )}

        {/* Volume count (volumes view) */}
        {viewMode === "volumes" && (
          <div className="border-t border-card-border px-6 py-3 bg-muted/50">
            <div className="text-sm text-muted-foreground">
              {volumeGroups.length} volumes • {issues.length} total{" "}
              {itemLabelPlural}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
