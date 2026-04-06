import { BookOpen, Library, TrendingUp } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

interface CollectionStatsProps {
  stats?: {
    total_series: number;
    total_issues: number;
    total_expected: number;
    completion_pct: number;
    comic_series?: number;
    comic_have?: number;
    comic_total?: number;
    manga_series?: number;
    manga_have?: number;
    manga_total?: number;
    manga_completion_pct?: number;
  };
  isLoading: boolean;
}

export default function CollectionStats({
  stats,
  isLoading,
}: CollectionStatsProps) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        {Array.from({ length: 3 }).map((_, i) => (
          <Card key={i}>
            <CardContent className="p-5">
              <Skeleton className="h-4 w-24 mb-3" />
              <Skeleton className="h-8 w-16" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  const hasManga = (stats?.manga_series ?? 0) > 0;

  const items = [
    {
      label: "Active Series",
      value: stats?.total_series ?? 0,
      subtitle: hasManga
        ? `${stats?.comic_series ?? 0} comics, ${stats?.manga_series ?? 0} manga`
        : undefined,
      icon: Library,
    },
    {
      label: "Issues Collected",
      value: stats?.total_issues ?? 0,
      subtitle: hasManga
        ? `${stats?.comic_have ?? 0} comic, ${stats?.manga_have ?? 0} manga`
        : undefined,
      icon: BookOpen,
    },
    {
      label: "Completion",
      value: `${stats?.completion_pct ?? 0}%`,
      subtitle: hasManga
        ? `Manga: ${stats?.manga_completion_pct ?? 0}%`
        : undefined,
      icon: TrendingUp,
    },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
      {items.map(({ label, value, subtitle, icon: Icon }) => (
        <Card key={label}>
          <CardContent className="p-5">
            <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
              <Icon className="w-4 h-4" />
              <span>{label}</span>
            </div>
            <p className="text-2xl font-bold tracking-tight">{value}</p>
            {subtitle && (
              <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
