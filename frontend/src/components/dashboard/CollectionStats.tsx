import { BookOpen, Library, TrendingUp } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

interface CollectionStatsProps {
  stats?: {
    total_series: number;
    total_issues: number;
    total_expected: number;
    completion_pct: number;
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

  const items = [
    {
      label: "Active Series",
      value: stats?.total_series ?? 0,
      icon: Library,
    },
    {
      label: "Issues Collected",
      value: stats?.total_issues ?? 0,
      icon: BookOpen,
    },
    {
      label: "Completion",
      value: `${stats?.completion_pct ?? 0}%`,
      icon: TrendingUp,
    },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
      {items.map(({ label, value, icon: Icon }) => (
        <Card key={label}>
          <CardContent className="p-5">
            <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
              <Icon className="w-4 h-4" />
              <span>{label}</span>
            </div>
            <p className="text-2xl font-bold tracking-tight">{value}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
