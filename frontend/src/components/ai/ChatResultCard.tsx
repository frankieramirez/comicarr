import { useNavigate } from "react-router-dom";
import type { ChatResult } from "@/hooks/useAiChat";

interface ChatResultCardProps {
  result: ChatResult;
  onNavigate?: () => void;
}

export function ChatResultCard({ result, onNavigate }: ChatResultCardProps) {
  const navigate = useNavigate();

  const comicId = result.ComicID;
  const name = result.ComicName || result.StoryArc || "Unknown";
  const year = result.ComicYear;
  const publisher = result.ComicPublisher;
  const image = result.ComicImage;
  const have = result.Have ?? result.have ?? 0;
  const total = result.Total ?? result.total ?? 0;
  const pct =
    result.pct ??
    (total > 0 ? Math.round((Number(have) / Number(total)) * 100) : 0);
  const status = result.Status;
  const issueNumber = result.Issue_Number;
  const gaps = result.gaps;

  const isClickable = !!comicId;

  const handleClick = () => {
    if (comicId) {
      if (onNavigate) onNavigate();
      navigate(`/series/${comicId}`);
    }
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={!isClickable}
      className={`w-full flex items-start gap-3 rounded-lg border border-border p-2.5 text-left transition-colors ${
        isClickable
          ? "hover:bg-accent hover:border-accent cursor-pointer"
          : "cursor-default"
      }`}
    >
      {image && (
        <img
          src={image}
          alt={String(name)}
          className="w-10 h-14 rounded object-cover flex-shrink-0 bg-muted"
          loading="lazy"
        />
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-1.5">
          <span className="text-sm font-medium text-foreground truncate">
            {name}
          </span>
          {issueNumber && (
            <span className="text-xs text-muted-foreground flex-shrink-0">
              #{issueNumber}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 mt-0.5">
          {year && (
            <span className="text-xs text-muted-foreground">{year}</span>
          )}
          {publisher && (
            <span className="text-xs text-muted-foreground">{publisher}</span>
          )}
          {status && (
            <span
              className={`text-xs px-1.5 py-0.5 rounded ${
                status === "Downloaded"
                  ? "bg-emerald-500/10 text-emerald-500"
                  : status === "Wanted"
                    ? "bg-amber-500/10 text-amber-500"
                    : status === "Snatched"
                      ? "bg-blue-500/10 text-blue-500"
                      : "bg-muted text-muted-foreground"
              }`}
            >
              {status}
            </span>
          )}
        </div>

        {total > 0 && (
          <div className="mt-1.5">
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-xs text-muted-foreground">
                {have}/{total} issues
                {gaps !== undefined && gaps > 0 && ` (${gaps} gaps)`}
              </span>
              <span className="text-xs text-muted-foreground">{pct}%</span>
            </div>
            <div className="w-full h-1.5 bg-muted rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  Number(pct) >= 100
                    ? "bg-emerald-500"
                    : Number(pct) >= 75
                      ? "bg-blue-500"
                      : Number(pct) >= 50
                        ? "bg-amber-500"
                        : "bg-orange-500"
                }`}
                style={{ width: `${Math.min(Number(pct), 100)}%` }}
              />
            </div>
          </div>
        )}
      </div>
    </button>
  );
}
