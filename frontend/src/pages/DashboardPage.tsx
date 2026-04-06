import RecentDownloads from "@/components/dashboard/RecentDownloads";
import UpcomingReleases from "@/components/dashboard/UpcomingReleases";
import CollectionStats from "@/components/dashboard/CollectionStats";
import AiInsightsPanel from "@/components/dashboard/AiInsightsPanel";
import AiDiscoveryBanner from "@/components/dashboard/AiDiscoveryBanner";
import ErrorDisplay from "@/components/ui/ErrorDisplay";
import { useDashboard } from "@/hooks/useDashboard";

export default function DashboardPage() {
  const { data, isLoading, error } = useDashboard();

  if (error) {
    return (
      <ErrorDisplay
        error={error}
        title="Unable to load dashboard"
        onRetry={() => window.location.reload()}
      />
    );
  }

  return (
    <div className="page-transition">
      <div className="mb-6">
        <h1 className="text-[32px] font-bold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Your library at a glance
        </p>
      </div>

      {!data?.ai_configured && !isLoading && <AiDiscoveryBanner />}

      <CollectionStats stats={data?.stats} isLoading={isLoading} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <RecentDownloads
          downloads={data?.recently_downloaded}
          isLoading={isLoading}
        />
        <UpcomingReleases
          releases={data?.upcoming_releases}
          isLoading={isLoading}
        />
      </div>

      {data?.ai_configured && <AiInsightsPanel activity={data?.ai_activity} />}
    </div>
  );
}
