import { Link } from "react-router-dom";
import { Calendar } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

interface UpcomingItem {
  ComicName: string;
  IssueNumber: string;
  IssueDate: string;
  Publisher: string;
  ComicID: string;
  Status: string;
}

interface UpcomingReleasesProps {
  releases?: UpcomingItem[];
  isLoading: boolean;
}

function formatReleaseDate(dateStr: string): string {
  if (!dateStr) return "";
  try {
    const date = new Date(dateStr + "T00:00:00");
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const diffMs = date.getTime() - today.getTime();
    const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Tomorrow";
    if (diffDays > 1 && diffDays <= 7) return `In ${diffDays} days`;
    return date.toLocaleDateString();
  } catch {
    return dateStr;
  }
}

export default function UpcomingReleases({
  releases,
  isLoading,
}: UpcomingReleasesProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <Skeleton className="h-5 w-40" />
        </CardHeader>
        <CardContent className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <div className="flex-1">
                <Skeleton className="h-4 w-40 mb-1" />
                <Skeleton className="h-3 w-24" />
              </div>
              <Skeleton className="h-5 w-16" />
            </div>
          ))}
        </CardContent>
      </Card>
    );
  }

  const items = releases ?? [];

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Calendar className="w-4 h-4" />
          Upcoming This Week
        </CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">
            No upcoming releases this week
          </p>
        ) : (
          <div className="space-y-3">
            {items.map((item, idx) => (
              <Link
                key={`${item.ComicID}-${item.IssueNumber}-${idx}`}
                to={`/series/${item.ComicID}`}
                className="flex items-center gap-3 rounded-lg p-2 -mx-2 transition-colors hover:bg-muted/50"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">
                    {item.ComicName}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    #{item.IssueNumber} &middot; {item.Publisher}
                  </p>
                </div>
                <span className="text-xs text-muted-foreground shrink-0">
                  {formatReleaseDate(item.IssueDate)}
                </span>
              </Link>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
