import { useState, useEffect, useRef, SyntheticEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Check, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAddComic } from '@/hooks/useSearch';
import { useToast } from '@/components/ui/toast';
import type { SearchResult } from '@/types';

interface ComicCardProps {
  comic: SearchResult;
}

interface AddByIdEventDetail {
  comicid: string;
  status: 'success' | 'failure';
  message?: string;
}

export default function ComicCard({ comic }: ComicCardProps) {
  const [isAdded, setIsAdded] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const addComicMutation = useAddComic();
  const { addToast } = useToast();
  const navigate = useNavigate();
  const comicIdRef = useRef<string | null>(null);

  // Listen for SSE events when a comic is being added
  useEffect(() => {
    if (!isProcessing || !comicIdRef.current) return;

    const handleAddById = (event: CustomEvent<string>) => {
      try {
        const data: AddByIdEventDetail = JSON.parse(event.detail);
        
        // Check if this event is for our comic
        if (data.comicid === comicIdRef.current) {
          if (data.status === 'success') {
            // Navigate to series detail page
            navigate(`/series/${comicIdRef.current}`);
            setIsProcessing(false);
            comicIdRef.current = null;
          } else if (data.status === 'failure') {
            addToast({
              type: 'error',
              title: 'Failed to Add Series',
              description: data.message || 'An error occurred while adding the series.',
            });
            setIsProcessing(false);
            setIsAdded(false);
            comicIdRef.current = null;
          }
        }
      } catch (error) {
        console.error('Error parsing addbyid event:', error);
      }
    };

    // Listen for custom event dispatched by useServerEvents
    window.addEventListener('comic-added', handleAddById as EventListener);
    
    return () => {
      window.removeEventListener('comic-added', handleAddById as EventListener);
    };
  }, [isProcessing, navigate, addToast]);

  const handleAddComic = async (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();

    try {
      comicIdRef.current = comic.comicid ?? null;
      setIsProcessing(true);
      
      await addComicMutation.mutateAsync(comic.comicid ?? comic.id);
      setIsAdded(true);
      addToast({
        type: 'success',
        title: 'Adding Comic...',
        description: `${comic.name} is being added to your library. Please wait...`,
        duration: 5000,
      });
    } catch (err) {
      setIsProcessing(false);
      setIsAdded(false);
      comicIdRef.current = null;
      addToast({
        type: 'error',
        title: 'Failed to Add Comic',
        description: err instanceof Error ? err.message : 'Unknown error',
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
            onError={(e: SyntheticEvent<HTMLImageElement>) => {
              e.currentTarget.src = 'https://via.placeholder.com/300x450?text=No+Cover';
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
          disabled={addComicMutation.isPending || isAdded || isProcessing}
          className="w-full h-8 text-xs mt-3"
          variant={isAdded ? 'outline' : 'default'}
          size="sm"
        >
          {isProcessing ? (
            <>
              <Loader2 className="w-3 h-3 mr-1 animate-spin" />
              Processing...
            </>
          ) : addComicMutation.isPending ? (
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
