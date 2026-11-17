import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGetWithTimeout, apiRequest } from "@/lib/api";
import type { WeekRef, WeeklyPullWeek } from "@/pages/weeklyReleaseRowKey";

export interface WeeklyRefreshResult {
  accepted: boolean;
  state: "queued" | "running" | "paused";
  message?: string;
  error?: string;
}

export interface ScheduledJob {
  id: string;
  name: string;
  next_run_time: string | null;
  trigger: string;
  status?: string | null;
  last_success_timestamp?: number | null;
  last_failure_timestamp?: number | null;
  last_error?: string | null;
}

interface JobsResponse {
  jobs: ScheduledJob[];
}

export function useWeeklyRefresh() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<WeeklyRefreshResult>("POST", "/api/weekly/refresh"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["system", "jobs"] });
    },
  });
}

export function useScheduledJobs(enabled: boolean) {
  return useQuery<JobsResponse>({
    queryKey: ["system", "jobs"],
    queryFn: () => apiRequest<JobsResponse>("GET", "/api/system/jobs"),
    enabled,
    staleTime: 0,
    refetchInterval: (query) => {
      const weekly = query.state.data?.jobs.find((job) => job.id === "weekly");
      const status = weekly?.status?.toLowerCase();
      return status === "running" || status === "queued" ? 2_000 : false;
    },
  });
}

/** How long Releases waits for a week before showing an error with Retry. */
export const RELEASES_TIMEOUT_MS = 30_000;

/** One week of the industry pull list; no `week` means the current week. */
export function useWeeklyPullList(week: WeekRef | null) {
  return useQuery({
    queryKey: ["weekly", week?.year ?? "current", week?.week ?? "current"],
    queryFn: ({ signal }) =>
      apiGetWithTimeout<WeeklyPullWeek>(
        week
          ? `/api/weekly?week=${encodeURIComponent(week.week)}&year=${encodeURIComponent(week.year)}`
          : "/api/weekly",
        RELEASES_TIMEOUT_MS,
        signal,
      ),
    staleTime: 5 * 60 * 1000,
    // MangaUpdates fills in on a background thread; poll until it is done.
    refetchInterval: (query) =>
      query.state.data?.manga?.status === "refreshing" ? 5_000 : false,
  });
}

export interface AddFromWeekInput {
  rowid: number;
  want: boolean;
}

export interface AddFromWeekResult {
  success: boolean;
  comicid?: string;
  want_queued?: boolean;
}

/** Add a pull-list row's series, optionally marking that issue Wanted once it lands. */
export function useAddFromWeek() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: AddFromWeekInput) =>
      apiRequest<AddFromWeekResult>("POST", "/api/weekly/add", input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });
}
