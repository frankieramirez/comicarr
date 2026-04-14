import { useState, SyntheticEvent } from "react";
import { Link } from "react-router-dom";
import { Download, ImageOff } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

interface DownloadItem {
  ComicName: string;
  Issue_Number: string;
  DateAdded: string;
  Status: string;
  Provider: string;
  ComicID: string;
  IssueID: string;
  ComicImage: string | null;
}

interface RecentDownloadsProps {
  downloads?: DownloadItem[];
  isLoading: boolean;
}

function formatDate(dateStr: string): string {
  if (!dateStr) return "";
  try {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));

    if (diffHours < 1) return "Just now";
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays === 1) return "Yesterday";
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  } catch {
    return dateStr;
  }
}

function DownloadRow({ item }: { item: DownloadItem }) {
  const [imageError, setImageError] = useState(false);

  const fallback = (
    <div className="h-10 w-10 rounded bg-muted flex items-center justify-center flex-shrink-0">
      <ImageOff className="w-4 h-4 text-muted-foreground" />
    </div>
  );

  return (
    <Link
      to={`/library/${item.ComicID}`}
      className="flex items-center gap-3 rounded-lg p-2 -mx-2 transition-colors hover:bg-muted/50"
    >
      {item.ComicID && !imageError ? (
        <img
          src={`/api/metadata/art/${item.ComicID}`}
          alt={item.ComicName}
          className="h-10 w-10 rounded object-cover flex-shrink-0"
          onError={(e: SyntheticEvent<HTMLImageElement>) => {
            setImageError(true);
            e.currentTarget.style.display = "none";
          }}
        />
      ) : (
        fallback
      )}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">{item.ComicName}</p>
        <p className="text-xs text-muted-foreground">
          #{item.Issue_Number} &middot; {formatDate(item.DateAdded)}
        </p>
      </div>
      {item.Provider && (
        <Badge variant="secondary" className="text-[10px] shrink-0">
          {item.Provider}
        </Badge>
      )}
    </Link>
  );
}

export default function RecentDownloads({
  downloads,
  isLoading,
}: RecentDownloadsProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <Skeleton className="h-5 w-40" />
        </CardHeader>
        <CardContent className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <Skeleton className="h-10 w-10 rounded" />
              <div className="flex-1">
                <Skeleton className="h-4 w-32 mb-1" />
                <Skeleton className="h-3 w-20" />
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    );
  }

  const items = downloads ?? [];

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Download className="w-4 h-4" />
          Recent Downloads
        </CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">
            No recent downloads
          </p>
        ) : (
          <div className="space-y-3">
            {items.map((item, idx) => (
              <DownloadRow key={`${item.IssueID}-${idx}`} item={item} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
