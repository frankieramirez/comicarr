import { useState, type SyntheticEvent } from "react";
import { BookOpen, ImageOff } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import StatusBadge from "@/components/StatusBadge";
import { getProgressPercentage } from "@/lib/series-utils";
import type { Comic } from "@/types";

interface SeriesCardProps {
  comic: Comic;
  onClick?: () => void;
}

export default function SeriesCard({ comic, onClick }: SeriesCardProps) {
  const [imageError, setImageError] = useState(false);

  const src =
    comic.ComicImage ||
    (comic.ComicID ? `/api/metadata/art/${comic.ComicID}` : null);

  const percentage = getProgressPercentage(comic);
  const have = parseInt(String(comic.Have)) || 0;
  const total = parseInt(String(comic.Total)) || 0;
  const isManga = comic.ContentType?.toLowerCase() === "manga";

  return (
    <div
      onClick={onClick}
      className="bg-card border-card-border card-shadow hover:shadow-lg hover:border-primary/30 transition-all duration-200 group rounded-lg border overflow-hidden flex flex-col h-full cursor-pointer"
    >
      {/* Cover Image */}
      <div className="aspect-[2/3] bg-muted relative overflow-hidden flex-shrink-0">
        {!imageError && src ? (
          <img
            src={src}
            alt={comic.ComicName}
            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
            loading="lazy"
            onError={(e: SyntheticEvent<HTMLImageElement>) => {
              setImageError(true);
              e.currentTarget.style.display = "none";
            }}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-muted-foreground/50">
            <ImageOff className="w-8 h-8" />
          </div>
        )}

        {/* Status Badge Overlay */}
        <div className="absolute top-2 right-2">
          <StatusBadge status={comic.Status} />
        </div>

        {/* Manga Badge Overlay */}
        {isManga && (
          <div className="absolute top-2 left-2">
            <Badge variant="secondary" className="text-xs px-1.5 py-0">
              <BookOpen className="w-3 h-3 mr-1" />
              Manga
            </Badge>
          </div>
        )}
      </div>

      {/* Info Section */}
      <div className="p-3 flex flex-col flex-grow">
        <div className="flex-grow">
          <h3 className="font-semibold text-sm line-clamp-2 leading-tight">
            {comic.ComicName}
          </h3>
          {comic.ComicYear && (
            <p className="text-xs text-muted-foreground mt-0.5">
              ({comic.ComicYear})
            </p>
          )}
          {comic.ComicPublisher && (
            <p className="text-xs text-muted-foreground mt-0.5 truncate">
              {comic.ComicPublisher}
            </p>
          )}
        </div>

        {/* Progress */}
        <div className="mt-2 space-y-1">
          <div className="w-full bg-border rounded-full h-1.5 overflow-hidden">
            <div
              className="h-full rounded-full transition-all bg-gradient-to-r from-[#FF5C00] to-[#FF8A4C]"
              style={{ width: `${percentage}%` }}
            />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground font-mono">
              {have} / {total}
            </span>
            <span className="text-xs text-muted-foreground font-mono">
              {percentage}%
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
