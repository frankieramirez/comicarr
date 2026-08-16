import { useNavigate } from "react-router-dom";
import type { ChatResult } from "@/types/chat";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ArrowUpRight } from "lucide-react";
import { seriesCoverSrc } from "@/lib/series-utils";

interface ChatResultCardProps {
  result: ChatResult;
}

export function ChatResultCard({ result }: ChatResultCardProps) {
  const navigate = useNavigate();
  const comicId = result.ComicID;
  const name = result.ComicName || result.StoryArc || "Unknown title";
  const have = Number(result.Have ?? result.have ?? 0);
  const total = Number(result.Total ?? result.total ?? 0);
  const pct = Number(
    result.pct ?? (total > 0 ? Math.round((have / total) * 100) : 0),
  );

  const coverSrc = seriesCoverSrc(comicId);
  const card = (
    <div className="group flex min-w-0 flex-1 items-center gap-3 text-left">
      <div className="h-16 w-11 shrink-0 overflow-hidden rounded-sm border bg-muted shadow-sm">
        {coverSrc ? (
          <img
            src={coverSrc}
            alt=""
            className="size-full object-cover transition-transform group-hover:scale-105 motion-reduce:transition-none"
            loading="lazy"
          />
        ) : (
          <div className="flex size-full items-center justify-center font-mono text-[9px] text-muted-foreground">
            NO COVER
          </div>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="truncate font-medium text-foreground">{name}</span>
          {result.Issue_Number && (
            <span className="mono-meta shrink-0">#{result.Issue_Number}</span>
          )}
          {result.ComicYear && (
            <span className="mono-meta shrink-0">{result.ComicYear}</span>
          )}
          {result.ComicPublisher && (
            <span className="mono-meta min-w-0 truncate">
              {result.ComicPublisher}
            </span>
          )}
          {result.Status && (
            <Badge variant="secondary" className="ml-auto shrink-0 uppercase">
              {result.Status}
            </Badge>
          )}
        </div>
        {total > 0 && (
          <div className="mt-2 flex items-center gap-2">
            <div className="h-1 flex-1 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary"
                style={{ width: `${Math.min(Math.max(pct, 0), 100)}%` }}
              />
            </div>
            <span className="mono-meta shrink-0">
              {have}/{total}
            </span>
          </div>
        )}
      </div>
      {comicId && <ArrowUpRight className="shrink-0 text-muted-foreground" />}
    </div>
  );

  if (!comicId) {
    return <div className="rounded-lg border bg-card p-3">{card}</div>;
  }

  return (
    <Button
      type="button"
      variant="ghost"
      className="h-auto w-full justify-start rounded-lg border bg-card p-3 hover:bg-accent"
      onClick={() => navigate(`/library/${comicId}`)}
    >
      {card}
    </Button>
  );
}
