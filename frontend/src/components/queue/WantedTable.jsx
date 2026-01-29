import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
} from '@tanstack/react-table';
import { X, ChevronUp, ChevronDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import StatusBadge from '@/components/StatusBadge';
import { useUnqueueIssue } from '@/hooks/useSeries';

export default function WantedTable({ issues = [], pagination, onNextPage, onPrevPage, onSelectionChange }) {
  const navigate = useNavigate();
  const [sorting, setSorting] = useState([{ id: 'DateAdded', desc: true }]);
  const [rowSelection, setRowSelection] = useState({});
  const unqueueIssueMutation = useUnqueueIssue();

  const handleUnqueueIssue = (e, issueId) => {
    e.stopPropagation();
    unqueueIssueMutation.mutate(issueId);
  };

  const handleRowClick = (comicId) => {
    navigate(`/series/${comicId}`);
  };

  const columns = [
    {
      id: 'select',
      header: ({ table }) => (
        <Checkbox
          checked={table.getIsAllRowsSelected()}
          indeterminate={table.getIsSomeRowsSelected() && !table.getIsAllRowsSelected()}
          onChange={table.getToggleAllRowsSelectedHandler()}
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          checked={row.getIsSelected()}
          onChange={row.getToggleSelectedHandler()}
          onClick={(e) => e.stopPropagation()}
        />
      ),
      size: 40,
    },
    {
      accessorKey: 'cover',
      header: '',
      cell: ({ row }) => {
        const [imageError, setImageError] = useState(false);
        const comicId = row.original.ComicID;

        return (
          <div className="w-12 h-16 bg-gray-200 rounded overflow-hidden flex-shrink-0">
            {!imageError && comicId ? (
              <img
                src={`/api?apikey=${localStorage.getItem('apiKey')}&cmd=getComic&id=${comicId}`}
                alt=""
                className="w-full h-full object-cover"
                onError={() => setImageError(true)}
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-gray-400 text-xs">
                N/A
              </div>
            )}
          </div>
        );
      },
      size: 60,
    },
    {
      accessorKey: 'ComicName',
      header: 'Series',
      cell: ({ row }) => (
        <div>
          <div className="font-medium">{row.original.ComicName}</div>
          {row.original.ComicYear && (
            <div className="text-sm text-gray-500">({row.original.ComicYear})</div>
          )}
        </div>
      ),
    },
    {
      accessorKey: 'Issue_Number',
      header: '#',
      cell: ({ getValue }) => (
        <span className="font-mono text-sm">{getValue() || 'N/A'}</span>
      ),
    },
    {
      accessorKey: 'IssueName',
      header: 'Issue Name',
      cell: ({ getValue }) => {
        const name = getValue();
        return name ? (
          <span className="text-sm text-gray-700">{name}</span>
        ) : (
          <span className="text-sm text-gray-400">N/A</span>
        );
      },
    },
    {
      accessorKey: 'DateAdded',
      header: 'Date Added',
      cell: ({ getValue }) => {
        const date = getValue();
        if (!date) return <span className="text-gray-400">N/A</span>;
        return <span className="text-sm">{date}</span>;
      },
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
        const issueId = row.original.IssueID;

        return (
          <div className="flex items-center space-x-2">
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
    onRowSelectionChange: (updater) => {
      setRowSelection(updater);
      // Notify parent of selection changes
      if (onSelectionChange) {
        const newSelection = typeof updater === 'function' ? updater(rowSelection) : updater;
        const selectedIds = Object.keys(newSelection).map((index) => issues[index]?.IssueID).filter(Boolean);
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
      <div className="text-center py-8 text-gray-500">
        No wanted issues in queue.
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
              <tr
                key={row.id}
                onClick={() => handleRowClick(row.original.ComicID)}
                className="hover:bg-gray-50 cursor-pointer transition-colors"
              >
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
      {pagination && (
        <div className="border-t border-gray-200 px-6 py-3 flex items-center justify-between bg-gray-50">
          <div className="text-sm text-gray-600">
            Showing {pagination.offset + 1} to {Math.min(pagination.offset + pagination.limit, pagination.total)} of {pagination.total} issues
          </div>
          <div className="flex items-center space-x-2">
            <Button
              variant="outline"
              size="sm"
              onClick={onPrevPage}
              disabled={pagination.offset === 0}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={onNextPage}
              disabled={!pagination.has_more}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
