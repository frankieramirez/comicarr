import { useState, type SyntheticEvent } from "react";
import { ImageOff } from "lucide-react";
import { getProgressPercentage, seriesCoverSrc } from "@/lib/series-utils";
import type { Comic } from "@/types";

interface SeriesCardProps {
  comic: Comic;
  onClick?: () => void;
}

/**
 * v2 library card: the cover carries the card. A hairline progress bar sits
 * on the cover's bottom edge; title, held count and year sit underneath.
 */
export default function SeriesCard({ comic, onClick }: SeriesCardProps) {
  const [imageError, setImageError] = useState(false);

  const src = seriesCoverSrc(comic.ComicID);

  const percentage = getProgressPercentage(comic);
  const have = parseInt(String(comic.Have)) || 0;
  const total = parseInt(String(comic.Total)) || 0;
  const isPaused = comic.Status?.toLowerCase() === "paused";

  return (
    <div
      {...(onClick && {
        role: "link",
        tabIndex: 0,
        onKeyDown: (e: React.KeyboardEvent) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onClick();
          }
        },
      })}
      onClick={onClick}
      className={`group flex h-full min-w-0 flex-col rounded-md ${onClick ? "cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-2 focus-visible:ring-offset-background" : ""}`}
    >
      <div className="relative aspect-[2/3] flex-shrink-0 overflow-hidden rounded-md bg-surface-2">
        {!imageError && src ? (
          <img
            src={src}
            alt={comic.ComicName}
            className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-[1.03]"
            loading="lazy"
            onError={(e: SyntheticEvent<HTMLImageElement>) => {
              setImageError(true);
              e.currentTarget.style.display = "none";
            }}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-muted-foreground">
            <ImageOff className="h-7 w-7" />
          </div>
        )}

        {isPaused && (
          <span className="absolute left-2 top-2 inline-flex items-center gap-1.5 rounded-md bg-background/85 px-1.5 py-0.5 text-[11px] text-foreground backdrop-blur-sm">
            <span
              className="size-1.5 rounded-full"
              style={{ background: "var(--status-paused)" }}
              aria-hidden="true"
            />
            Paused
          </span>
        )}

        {/* Held share, on the cover's bottom edge. */}
        <div
          className="absolute inset-x-0 bottom-0 h-[3px] bg-black/40"
          aria-hidden="true"
        >
          <div
            className="h-full"
            style={{
              width: `${percentage}%`,
              background: "var(--status-downloaded)",
            }}
          />
        </div>
      </div>

      <div className="mt-2 min-w-0">
        <h3 className="truncate text-[13px] font-medium leading-tight text-foreground">
          {comic.ComicName}
        </h3>
        <div className="mono-meta mt-1 flex items-center justify-between">
          <span>
            {have} / {total}
          </span>
          {comic.ComicYear && <span>{comic.ComicYear}</span>}
        </div>
      </div>
    </div>
  );
}
