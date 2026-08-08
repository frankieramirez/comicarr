import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";

/**
 * One query per dashboard panel.
 *
 * There is no aggregate `/api/dashboard` read: a single fan-in payload makes
 * one broken source blank the whole page, and an unavailable panel then looks
 * exactly like an empty one. Each hook below backs exactly one panel, so a
 * failure is scoped to that panel and retried there
 * (docs/architecture/dashboard-spec.md §5).
 */

interface DashboardActivityEvent {
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

export interface DashboardQueueItem {
  ID: string;
  series: string;
  filename: string;
  status: string | null;
  updated_date: string | null;
  site: string | null;
  comicid: string | null;
}

export interface DashboardLibraryStats {
  total_series: number;
  total_issues: number;
  total_expected: number;
  completion_pct: number;
}

interface DashboardLibraryResponse {
  stats: DashboardLibraryStats;
}

interface DashboardQueueResponse {
  count: number;
  items: DashboardQueueItem[];
}

interface DashboardActivityResponse {
  events: DashboardActivityEvent[];
  days: number;
}

interface DashboardUpcomingResponse {
  releases: DashboardUpcoming[];
}

export interface DashboardScanTargets {
  comic: boolean;
  manga: boolean;
}

const PANEL_STALE_TIME = 2 * 60 * 1000;

/** KPI strip: series, issues held, and completion. */
export function useDashboardLibrary() {
  return useQuery<DashboardLibraryResponse>({
    queryKey: ["dashboard", "library"],
    queryFn: () =>
      apiRequest<DashboardLibraryResponse>("GET", "/api/dashboard/library"),
    staleTime: PANEL_STALE_TIME,
  });
}

/** Active queue: the count on the KPI strip and the preview below it. */
export function useDashboardQueue() {
  return useQuery<DashboardQueueResponse>({
    queryKey: ["dashboard", "queue"],
    queryFn: () =>
      apiRequest<DashboardQueueResponse>("GET", "/api/dashboard/queue"),
    staleTime: PANEL_STALE_TIME,
  });
}

/** Recent activity preview, bounded to the window the response reports. */
export function useDashboardActivity() {
  return useQuery<DashboardActivityResponse>({
    queryKey: ["dashboard", "activity"],
    queryFn: () =>
      apiRequest<DashboardActivityResponse>("GET", "/api/dashboard/activity"),
    staleTime: PANEL_STALE_TIME,
  });
}

/** This week's releases for series already in the library. */
export function useDashboardUpcoming() {
  return useQuery<DashboardUpcomingResponse>({
    queryKey: ["dashboard", "upcoming"],
    queryFn: () =>
      apiRequest<DashboardUpcomingResponse>("GET", "/api/dashboard/upcoming"),
    staleTime: PANEL_STALE_TIME,
  });
}

/** Which libraries the header's scan action can start. */
export function useDashboardScanTargets() {
  return useQuery<DashboardScanTargets>({
    queryKey: ["dashboard", "scan-targets"],
    queryFn: () =>
      apiRequest<DashboardScanTargets>("GET", "/api/dashboard/scan-targets"),
    staleTime: PANEL_STALE_TIME,
  });
}
