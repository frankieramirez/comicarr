import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAddComic } from '@/hooks/useSearch';
import { useToast } from '@/components/ui/toast';

export default function ComicCard({ comic }) {
  const [isAdded, setIsAdded] = useState(false);
  const addComicMutation = useAddComic();
  const { addToast } = useToast();
  const navigate = useNavigate();

  const handleAddComic = async (e) => {
    e.stopPropagation();

    try {
      await addComicMutation.mutateAsync(comic.comicid);
      setIsAdded(true);
      addToast({
        type: 'success',
        title: 'Comic Added',
        description: `${comic.name} has been added to your library.`,
        duration: 3000,
      });

      // Navigate to the series detail page after a short delay
      setTimeout(() => {
        navigate(`/series/${comic.comicid}`);
      }, 1000);
    } catch (error) {
      addToast({
        type: 'error',
        title: 'Failed to Add Comic',
        description: error.message,
      });
    }
  };

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm hover:shadow-md transition-shadow overflow-hidden">
      {/* Cover Image */}
      <div className="aspect-[2/3] bg-gray-100 relative">
        {comic.image ? (
          <img
            src={comic.image}
            alt={comic.name}
            className="w-full h-full object-cover"
            onError={(e) => {
              e.target.src = 'https://via.placeholder.com/300x450?text=No+Cover';
            }}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-gray-400">
            No Cover
          </div>
        )}
      </div>

      {/* Comic Info */}
      <div className="p-4 space-y-3">
        <div>
          <h3 className="font-semibold text-lg line-clamp-2">{comic.name}</h3>
          {comic.comicyear && (
            <p className="text-sm text-gray-600">({comic.comicyear})</p>
          )}
        </div>

        {comic.publisher && (
          <p className="text-sm text-gray-500">
            <span className="font-medium">Publisher:</span> {comic.publisher}
          </p>
        )}

        {comic.issues && (
          <p className="text-sm text-gray-500">
            <span className="font-medium">Issues:</span> {comic.issues}
          </p>
        )}

        {comic.description && (
          <p className="text-xs text-gray-500 line-clamp-3">
            {comic.description}
          </p>
        )}

        {/* Add Button */}
        <Button
          onClick={handleAddComic}
          disabled={addComicMutation.isPending || isAdded}
          className="w-full"
          variant={isAdded ? 'outline' : 'default'}
        >
          {addComicMutation.isPending ? (
            'Adding...'
          ) : isAdded ? (
            <>
              <Check className="w-4 h-4 mr-2" />
              Added
            </>
          ) : (
            <>
              <Plus className="w-4 h-4 mr-2" />
              Add to Library
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
