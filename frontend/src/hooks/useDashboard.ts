import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";

interface DashboardDownload {
  ComicName: string;
  Issue_Number: string;
  DateAdded: string;
  Status: string;
  Provider: string;
  ComicID: string;
  IssueID: string;
  ComicImage: string | null;
}

interface DashboardUpcoming {
  ComicName: string;
  IssueNumber: string;
  IssueDate: string;
  Publisher: string;
  ComicID: string;
  Status: string;
}

interface DashboardStats {
  total_series: number;
  total_issues: number;
  total_expected: number;
  completion_pct: number;
}

interface DashboardAiActivity {
  timestamp: string;
  feature_type: string;
  action_description: string;
  prompt_tokens: number;
  completion_tokens: number;
  success: boolean;
}

export interface DashboardData {
  recently_downloaded: DashboardDownload[];
  upcoming_releases: DashboardUpcoming[];
  stats: DashboardStats;
  ai_activity: DashboardAiActivity[];
  ai_configured: boolean;
}

export function useDashboard() {
  return useQuery<DashboardData>({
    queryKey: ["dashboard"],
    queryFn: () => apiRequest<DashboardData>("GET", "/api/dashboard"),
    staleTime: 2 * 60 * 1000,
  });
}
