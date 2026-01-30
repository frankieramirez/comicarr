import { useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  ColumnDef,
  SortingState,
  RowSelectionState,
  CellContext,
  HeaderContext,
  Updater,
} from "@tanstack/react-table";
import { Download, X, ChevronUp, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import StatusBadge from "@/components/StatusBadge";
import { useQueueIssue, useUnqueueIssue } from "@/hooks/useSeries";
import type { UpcomingIssue } from "@/types";

interface UpcomingTableProps {
  issues?: UpcomingIssue[];
  onSelectionChange?: (selectedIds: string[]) => void;
}

export default function UpcomingTable({
  issues = [],
  onSelectionChange,
}: UpcomingTableProps) {
  const [sorting, setSorting] = useState<SortingState>([
    { id: "IssueDate", desc: false },
  ]);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const queueIssueMutation = useQueueIssue();
  const unqueueIssueMutation = useUnqueueIssue();

  const handleQueueIssue = (e: React.MouseEvent, issueId: string) => {
    e.stopPropagation();
    queueIssueMutation.mutate(issueId);
  };

  const handleUnqueueIssue = (e: React.MouseEvent, issueId: string) => {
    e.stopPropagation();
    unqueueIssueMutation.mutate(issueId);
  };

  const columns: ColumnDef<UpcomingIssue>[] = [
    {
      id: "select",
      header: ({ table }: HeaderContext<UpcomingIssue, unknown>) => (
        <Checkbox
          checked={table.getIsAllRowsSelected()}
          indeterminate={
            table.getIsSomeRowsSelected() && !table.getIsAllRowsSelected()
          }
          onChange={table.getToggleAllRowsSelectedHandler()}
        />
      ),
      cell: ({ row }: CellContext<UpcomingIssue, unknown>) => (
        <Checkbox
          checked={row.getIsSelected()}
          onChange={row.getToggleSelectedHandler()}
          onClick={(e) => e.stopPropagation()}
        />
      ),
      size: 40,
    },
    {
      accessorKey: "cover",
      header: "",
      cell: ({ row }: CellContext<UpcomingIssue, unknown>) => {
        const [imageError, setImageError] = useState(false);
        const comicId = row.original.ComicID;

        return (
          <div className="w-12 h-16 bg-gray-200 rounded overflow-hidden flex-shrink-0">
            {!imageError && comicId ? (
              <img
                src={`/api?apikey=${localStorage.getItem("apiKey")}&cmd=getComic&id=${comicId}`}
                alt=""
                className="w-full h-full object-cover"
                onError={() => setImageError(true)}
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-muted-foreground/70 text-xs">
                N/A
              </div>
            )}
          </div>
        );
      },
      size: 60,
    },
    {
      accessorKey: "ComicName",
      header: "Series",
      cell: ({ row }: CellContext<UpcomingIssue, unknown>) => (
        <div>
          <div className="font-medium">{row.original.ComicName}</div>
          {row.original.ComicYear && (
            <div className="text-sm text-muted-foreground">
              ({row.original.ComicYear})
            </div>
          )}
        </div>
      ),
    },
    {
      accessorKey: "IssueNumber",
      header: "#",
      cell: ({ getValue }: CellContext<UpcomingIssue, unknown>) => (
        <span className="font-mono text-sm">
          {(getValue() as string) || "N/A"}
        </span>
      ),
    },
    {
      accessorKey: "IssueName",
      header: "Issue Name",
      cell: ({ getValue }: CellContext<UpcomingIssue, unknown>) => {
        const name = getValue() as string | undefined;
        return name ? (
          <span className="text-sm text-foreground">{name}</span>
        ) : (
          <span className="text-sm text-muted-foreground/70">N/A</span>
        );
      },
    },
    {
      accessorKey: "IssueDate",
      header: "Release Date",
      cell: ({ getValue }: CellContext<UpcomingIssue, unknown>) => {
        const date = getValue() as string | undefined;
        if (!date) return <span className="text-muted-foreground/70">N/A</span>;
        return <span className="text-sm">{date}</span>;
      },
    },
    {
      accessorKey: "Status",
      header: "Status",
      cell: ({ getValue }: CellContext<UpcomingIssue, unknown>) => (
        <StatusBadge status={getValue() as string} />
      ),
    },
    {
      id: "actions",
      header: "Actions",
      cell: ({ row }: CellContext<UpcomingIssue, unknown>) => {
        const status = row.original.Status?.toLowerCase();
        const issueId = row.original.IssueID;

        return (
          <div className="flex items-center space-x-2">
            {status === "wanted" || status === "skipped" ? (
              <>
                {status === "wanted" && (
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
                {status === "skipped" && (
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
            ) : status !== "downloaded" && status !== "snatched" ? (
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
  ];

  const table = useReactTable({
    data: issues,
    columns,
    state: {
      sorting,
      rowSelection,
    },
    onSortingChange: setSorting,
    onRowSelectionChange: (updater: Updater<RowSelectionState>) => {
      setRowSelection(updater);
      // Notify parent of selection changes
      if (onSelectionChange) {
        const newSelection =
          typeof updater === "function" ? updater(rowSelection) : updater;
        const selectedIds = Object.keys(newSelection)
          .map((index) => issues[parseInt(index)]?.IssueID)
          .filter(Boolean) as string[];
        onSelectionChange(selectedIds);
      }
    },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (row) => row.IssueID,
    enableRowSelection: true,
  });

  if (issues.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        No upcoming releases this week.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-card-border overflow-hidden bg-card">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-muted/50 border-b border-card-border">
            {table.getHeaderGroups().map((headerGroup) => (
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
                        {header.column.getCanSort() &&
                          header.column.getIsSorted() && (
                            <span className="text-muted-foreground/70">
                              {header.column.getIsSorted() === "asc" ? (
                                <ChevronUp className="w-4 h-4" />
                              ) : (
                                <ChevronDown className="w-4 h-4" />
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
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="hover:bg-muted/50 transition-colors">
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-6 py-4 whitespace-nowrap">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
