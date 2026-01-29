import { Link } from 'react-router-dom';
import { Plus } from 'lucide-react';
import { useSeries } from '@/hooks/useSeries';
import SeriesTable from '@/components/series/SeriesTable';
import { Button } from '@/components/ui/button';

export default function HomePage() {
  const { data: series = [], isLoading, error } = useSeries();

  if (error) {
    return (
      <div className="text-center py-12">
        <p className="text-red-600 text-lg">Failed to load series</p>
        <p className="text-gray-500 text-sm mt-2">{error.message}</p>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">My Series</h1>
        <Link to="/search">
          <Button className="flex items-center">
            <Plus className="w-4 h-4 mr-2" />
            Add Series
          </Button>
        </Link>
      </div>

      <SeriesTable data={series} isLoading={isLoading} />
    </div>
  );
}
