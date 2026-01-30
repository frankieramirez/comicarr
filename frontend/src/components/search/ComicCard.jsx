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
    <div className="bg-card border-card-border card-shadow hover:shadow-lg hover:border-primary/30 transition-all duration-200 group rounded-lg border overflow-hidden flex flex-col h-full">
      {/* Cover Image */}
      <div className="aspect-[2/3] bg-muted relative overflow-hidden flex-shrink-0">
        {comic.image ? (
          <img
            src={comic.image}
            alt={comic.name}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
            onError={(e) => {
              e.target.src = 'https://via.placeholder.com/300x450?text=No+Cover';
            }}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-muted-foreground">
            No Cover
          </div>
        )}
      </div>

      {/* Comic Info */}
      <div className="p-3 flex flex-col flex-grow">
        <div className="flex-grow">
          <h3 className="font-semibold text-sm line-clamp-2 leading-tight">{comic.name}</h3>
          {comic.comicyear && (
            <p className="text-xs text-muted-foreground mt-0.5">{comic.comicyear}</p>
          )}
        </div>

        {(comic.publisher || comic.issues) && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground mt-1">
            {comic.publisher && <span className="truncate">{comic.publisher}</span>}
            {comic.publisher && comic.issues && <span>·</span>}
            {comic.issues && <span>{comic.issues} issues</span>}
          </div>
        )}

        {/* Add Button - Always at bottom */}
        <Button
          onClick={handleAddComic}
          disabled={addComicMutation.isPending || isAdded}
          className="w-full h-8 text-xs mt-3"
          variant={isAdded ? 'outline' : 'default'}
          size="sm"
        >
          {addComicMutation.isPending ? (
            'Adding...'
          ) : isAdded ? (
            <>
              <Check className="w-3 h-3 mr-1" />
              Added
            </>
          ) : (
            <>
              <Plus className="w-3 h-3 mr-1" />
              Add
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
