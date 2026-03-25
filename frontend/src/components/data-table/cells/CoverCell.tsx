import { useState, SyntheticEvent } from "react";
import { BookOpen, ImageOff } from "lucide-react";
import { Badge } from "@/components/ui/badge";

interface CoverCellProps {
  comicId?: string;
  /** External image URL (e.g., from ComicVine). Takes precedence over API URL. */
  imageUrl?: string | null;
  /** Full variant shows title, year, and manga badge alongside the image */
  variant?: "thumbnail" | "full";
  title?: string;
  year?: string | null;
  isManga?: boolean;
}

export function CoverCell({
  comicId,
  imageUrl,
  variant = "thumbnail",
  title,
  year,
  isManga,
}: CoverCellProps) {
  const [imageError, setImageError] = useState(false);

  const src = imageUrl || (comicId ? `/api/metadata/art/${comicId}` : null);

  const thumbnail = (
    <div className="w-10 h-14 bg-muted rounded overflow-hidden flex-shrink-0">
      {!imageError && src ? (
        <img
          src={src}
          alt={title || ""}
          className="w-full h-full object-cover"
          loading="lazy"
          onError={(e: SyntheticEvent<HTMLImageElement>) => {
            setImageError(true);
            e.currentTarget.style.display = "none";
          }}
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-muted-foreground/50">
          <ImageOff className="w-4 h-4" />
        </div>
      )}
    </div>
  );

  if (variant === "thumbnail") return thumbnail;

  return (
    <div className="flex items-center space-x-3">
      {thumbnail}
      <div>
        <div className="flex items-center gap-2">
          <span className="font-medium">{title}</span>
          {isManga && (
            <Badge variant="secondary" className="text-xs px-1.5 py-0">
              <BookOpen className="w-3 h-3 mr-1" />
              Manga
            </Badge>
          )}
        </div>
        {year && <div className="text-sm text-muted-foreground">({year})</div>}
      </div>
    </div>
  );
}
