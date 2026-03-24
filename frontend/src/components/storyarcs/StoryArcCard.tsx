import { Link } from "react-router-dom";
import { BookMarked, Image as ImageIcon } from "lucide-react";
import type { StoryArc } from "@/types";

interface StoryArcCardProps {
  arc: StoryArc;
}

export default function StoryArcCard({ arc }: StoryArcCardProps) {
  const bannerUrl = arc.ArcImage ? `/cache/storyarcs/${arc.ArcImage}` : null;

  return (
    <Link
      to={`/story-arcs/${arc.StoryArcID}`}
      className="group block rounded-lg border border-card-border bg-card overflow-hidden transition-all hover:shadow-md hover:border-primary/30"
    >
      {/* Banner image or placeholder */}
      <div className="relative h-32 bg-muted overflow-hidden">
        {bannerUrl ? (
          <img
            src={bannerUrl}
            alt={arc.StoryArc}
            className="w-full h-full object-cover transition-transform group-hover:scale-105"
          />
        ) : (
          <div className="flex items-center justify-center h-full">
            <ImageIcon className="w-10 h-10 text-muted-foreground/40" />
          </div>
        )}
        {/* Gradient overlay */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/50 to-transparent" />
        {/* Completion badge overlay */}
        <div className="absolute bottom-2 right-2">
          <span className="inline-flex items-center rounded-full bg-black/60 px-2 py-0.5 text-xs font-medium text-white">
            {arc.Have}/{arc.Total}
          </span>
        </div>
      </div>

      {/* Card content */}
      <div className="p-3">
        <div className="flex items-start gap-2 mb-2">
          <BookMarked className="w-4 h-4 text-primary mt-0.5 shrink-0" />
          <h3 className="text-sm font-semibold text-foreground leading-tight line-clamp-2">
            {arc.StoryArc}
          </h3>
        </div>

        {arc.Publisher && (
          <p className="text-xs text-muted-foreground mb-2">{arc.Publisher}</p>
        )}

        {/* Progress bar */}
        <div className="w-full bg-muted rounded-full h-1.5 mb-1.5">
          <div
            className="h-1.5 rounded-full transition-all bg-primary"
            style={{ width: `${Math.min(arc.percent, 100)}%` }}
          />
        </div>

        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{Math.round(arc.percent)}% complete</span>
          {arc.SpanYears && <span>{arc.SpanYears}</span>}
        </div>
      </div>
    </Link>
  );
}
