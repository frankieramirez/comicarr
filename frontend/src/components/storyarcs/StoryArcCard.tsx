import { Link } from "react-router-dom";
import { Image as ImageIcon } from "lucide-react";
import type { StoryArc } from "@/types";

interface StoryArcCardProps {
  arc: StoryArc;
}

/** One story arc as a Library list row: art, name, held share, status. */
export default function StoryArcCard({ arc }: StoryArcCardProps) {
  const bannerUrl = arc.ArcImage ? `/cache/storyarcs/${arc.ArcImage}` : null;
  const missing = Math.max(0, arc.Total - arc.Have);
  const complete = arc.Total > 0 && missing === 0;
  const sub = [arc.Publisher, arc.SpanYears].filter(Boolean).join(" · ");

  return (
    <Link
      to={`/story-arcs/${arc.StoryArcID}`}
      className="grid grid-cols-[100px_minmax(0,1fr)] items-center gap-4 border-b border-border-subtle px-2 py-2.5 transition-colors hover:bg-surface-1 md:grid-cols-[100px_minmax(0,1fr)_220px_140px]"
    >
      <div className="h-[52px] w-[100px] overflow-hidden rounded-[4px] bg-surface-2">
        {bannerUrl ? (
          <img
            src={bannerUrl}
            alt={arc.StoryArc}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-muted-foreground">
            <ImageIcon className="size-5" />
          </div>
        )}
      </div>

      <div className="min-w-0">
        <h3 className="truncate text-sm font-medium text-foreground">
          {arc.StoryArc}
        </h3>
        {sub && (
          <p className="mt-0.5 truncate text-[13px] text-foreground-2">{sub}</p>
        )}
      </div>

      <div className="hidden items-center gap-3 md:flex">
        <div className="h-1 flex-1 overflow-hidden rounded-full bg-surface-3">
          <div
            className="h-full rounded-full"
            style={{
              width: `${Math.min(arc.percent, 100)}%`,
              background: "var(--status-downloaded)",
            }}
          />
        </div>
        <span className="shrink-0 font-mono text-xs text-foreground-2">
          {arc.Have} / {arc.Total}
        </span>
      </div>

      <div className="hidden items-center gap-1.5 text-[13px] md:flex">
        <span
          className="size-1.5 rounded-full"
          style={{
            background: complete ? "var(--status-active)" : "var(--text-muted)",
          }}
          aria-hidden="true"
        />
        <span className={complete ? "text-foreground" : "text-foreground-2"}>
          {complete ? "Complete" : `${missing} missing`}
        </span>
      </div>
    </Link>
  );
}
