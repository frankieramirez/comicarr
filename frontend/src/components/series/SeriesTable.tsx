import { useState, useMemo, SyntheticEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  flexRender,
  ColumnDef,
  SortingState,
  CellContext,
} from '@tanstack/react-table';
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import StatusBadge from '@/components/StatusBadge';
import { Skeleton } from '@/components/ui/skeleton';
import type { Comic } from '@/types';

interface SeriesTableProps {
  data?: Comic[];
  isLoading?: boolean;
}

export default function SeriesTable({ data = [], isLoading }: SeriesTableProps) {
  const navigate = useNavigate();
  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState('');

  const columns = useMemo<ColumnDef<Comic>[]>(
    () => [
      {
        accessorKey: 'ComicName',
        header: 'Comic',
        cell: ({ row }: CellContext<Comic, unknown>) => (
          <div className="flex items-center space-x-3">
            {row.original.ComicImage && (
              <img
                src={row.original.ComicImage}
                alt={row.original.ComicName}
                className="w-10 h-14 object-cover rounded shadow-sm"
                onError={(e: SyntheticEvent<HTMLImageElement>) => {
                  e.currentTarget.style.display = 'none';
                }}
              />
            )}
            <div>
              <div className="font-medium">{row.original.ComicName}</div>
              {row.original.ComicYear && (
                <div className="text-sm text-gray-500">({row.original.ComicYear})</div>
              )}
            </div>
          </div>
        ),
      },
      {
        accessorKey: 'ComicPublisher',
        header: 'Publisher',
        cell: ({ getValue }: CellContext<Comic, unknown>) => <span className="text-sm">{(getValue() as string) || 'N/A'}</span>,
      },
      {
        accessorKey: 'Status',
        header: 'Status',
        cell: ({ getValue }: CellContext<Comic, unknown>) => <StatusBadge status={getValue() as string} />,
      },
      {
        accessorKey: 'Total',
        header: 'Issues',
        cell: ({ row }: CellContext<Comic, unknown>) => (
          <div className="text-center">
            <span className="font-medium">{row.original.Have || 0}</span>
            <span className="text-gray-500"> / {row.original.Total || 0}</span>
          </div>
        ),
      },
      {
        id: 'progress',
        header: 'Progress',
        cell: ({ row }: CellContext<Comic, unknown>) => {
          const total = parseInt(String(row.original.Total)) || 0;
          const have = parseInt(String(row.original.Have)) || 0;
          const percentage = total > 0 ? Math.round((have / total) * 100) : 0;

          return (
            <div className="flex items-center space-x-2">
              <div className="flex-1 bg-muted rounded-full h-2 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${percentage}%`,
                    background: 'var(--gradient-brand)'
                  }}
                />
              </div>
              <span className="text-xs text-muted-foreground min-w-[3rem]">{percentage}%</span>
            </div>
          );
        },
      },
    ],
    []
  );

  const table = useReactTable({
    data,
    columns,
    state: {
      sorting,
      globalFilter,
    },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: {
      pagination: {
        pageSize: 20,
      },
    },
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-full max-w-sm" />
        {[...Array(10)].map((_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-muted-foreground text-lg">No series in your library yet.</p>
        <p className="text-muted-foreground/70 text-sm mt-2">
          Use the search page to add comics to your library.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Search */}
      <div className="flex items-center space-x-2">
        <Input
          placeholder="Search series..."
          value={globalFilter ?? ''}
          onChange={(e) => setGlobalFilter(e.target.value)}
          className="max-w-sm"
        />
        <span className="text-sm text-muted-foreground">
          {table.getFilteredRowModel().rows.length} series
        </span>
      </div>

      {/* Table */}
      <div className="rounded-lg border-card-border bg-card card-shadow overflow-hidden">
        <div className="overflow-x-auto custom-scrollbar">
          <table className="w-full">
            <thead className="bg-muted/50 border-card-border backdrop-blur-sm border-b">
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
                              ? 'flex items-center space-x-1 cursor-pointer select-none hover:text-foreground'
                              : ''
                          }
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          <span>
                            {flexRender(header.column.columnDef.header, header.getContext())}
                          </span>
                          {header.column.getCanSort() && (
                            <span className="text-gray-400">
                              {header.column.getIsSorted() === 'asc' ? (
                                <ChevronUp className="w-4 h-4" />
                              ) : header.column.getIsSorted() === 'desc' ? (
                                <ChevronDown className="w-4 h-4" />
                              ) : (
                                <ChevronsUpDown className="w-4 h-4" />
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
                <tr
                  key={row.id}
                  onClick={() => navigate(`/series/${row.original.ComicID}`)}
                  className="hover:bg-accent/50 cursor-pointer transition-colors"
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
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between">
        <div className="text-sm text-gray-500">
          Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
        </div>
        <div className="flex items-center space-x-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
