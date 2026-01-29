import { useState } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
} from '@tanstack/react-table';
import { Download, X, MoreVertical, ChevronUp, ChevronDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import StatusBadge from '@/components/StatusBadge';
import { useQueueIssue, useUnqueueIssue } from '@/hooks/useSeries';

export default function IssuesTable({ issues = [] }) {
  const [sorting, setSorting] = useState([{ id: 'Int_IssueNumber', desc: false }]);
  const queueIssueMutation = useQueueIssue();
  const unqueueIssueMutation = useUnqueueIssue();

  const handleQueueIssue = (e, issueId) => {
    e.stopPropagation();
    queueIssueMutation.mutate(issueId);
  };

  const handleUnqueueIssue = (e, issueId) => {
    e.stopPropagation();
    unqueueIssueMutation.mutate(issueId);
  };

  const columns = [
    {
      accessorKey: 'Int_IssueNumber',
      header: '#',
      cell: ({ getValue }) => (
        <span className="font-mono text-sm">{getValue() || 'N/A'}</span>
      ),
    },
    {
      accessorKey: 'IssueName',
      header: 'Issue Name',
      cell: ({ row }) => (
        <div>
          <div className="font-medium">{row.original.Issue_Number}</div>
          {row.original.IssueName && (
            <div className="text-sm text-gray-500">{row.original.IssueName}</div>
          )}
        </div>
      ),
    },
    {
      accessorKey: 'IssueDate',
      header: 'Release Date',
      cell: ({ getValue }) => {
        const date = getValue();
        if (!date) return <span className="text-gray-400">N/A</span>;
        return <span className="text-sm">{date}</span>;
      },
    },
    {
      accessorKey: 'Status',
      header: 'Status',
      cell: ({ getValue }) => <StatusBadge status={getValue()} />,
    },
    {
      id: 'actions',
      header: 'Actions',
      cell: ({ row }) => {
        const status = row.original.Status?.toLowerCase();
        const issueId = row.original.IssueID;

        return (
          <div className="flex items-center space-x-2">
            {status === 'wanted' || status === 'skipped' ? (
              <>
                {status === 'wanted' && (
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
                {status === 'skipped' && (
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
            ) : status !== 'downloaded' && status !== 'snatched' ? (
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
    },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (issues.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500">
        No issues found for this series.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-200 overflow-hidden bg-white">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-200">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                  >
                    {header.isPlaceholder ? null : (
                      <div
                        className={
                          header.column.getCanSort()
                            ? 'flex items-center space-x-1 cursor-pointer select-none hover:text-gray-700'
                            : ''
                        }
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        <span>
                          {flexRender(header.column.columnDef.header, header.getContext())}
                        </span>
                        {header.column.getCanSort() && header.column.getIsSorted() && (
                          <span className="text-gray-400">
                            {header.column.getIsSorted() === 'asc' ? (
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
          <tbody className="bg-white divide-y divide-gray-200">
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="hover:bg-gray-50 transition-colors">
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
