import { useEffect, useState, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { useUpcoming } from "@/hooks/useQueue";
import { useQueryClient } from "@tanstack/react-query";
import PageHeader, { Tab, TabRow } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import {
  useScheduledJobs,
  useWeeklyPullList,
  useWeeklyRefresh,
} from "@/hooks/useWeekly";
import IndustryReleasesView from "@/components/releases/IndustryReleasesView";
import MyReleasesView from "@/components/releases/MyReleasesView";
import WeekBar from "@/components/releases/WeekBar";
import type { WeekRef } from "@/pages/weeklyReleaseRowKey";

function readWeek(params: URLSearchParams): WeekRef | null {
  const week = params.get("week");
  const year = params.get("year");
  return week && year ? { week, year } : null;
}

type ReleasesView = "mine" | "all";

export default function ReleasesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const viewParam = searchParams.get("view");
  const currentView: ReleasesView = viewParam === "all" ? "all" : "mine";
  const selectedWeek = readWeek(searchParams);
  const { data: week } = useWeeklyPullList(selectedWeek);
  const mine = useUpcoming(true, selectedWeek);
  const weeklyRefresh = useWeeklyRefresh();
  const queryClient = useQueryClient();
  const [refreshRequested, setRefreshRequested] = useState(false);
  const [refreshObservedActive, setRefreshObservedActive] = useState(false);
  const refreshAccepted = useRef(false);
  const refreshInvalidated = useRef(false);
  const { data: jobs } = useScheduledJobs(refreshRequested);
  const { addToast } = useToast();
  const weeklyJob = jobs?.jobs.find((job) => job.id === "weekly");
  const weeklyStatus = weeklyJob?.status?.toLowerCase();
  const refreshMessage = !refreshRequested
    ? null
    : weeklyStatus === "queued"
      ? "Refresh queued — it will start shortly."
      : weeklyStatus === "running"
        ? "Refreshing releases…"
        : weeklyStatus === "error"
          ? weeklyJob?.last_error ||
            "Refresh failed. Check the pull source, then retry."
          : weeklyStatus === "waiting" && refreshObservedActive
            ? "Releases refreshed."
            : "Refresh queued — it will start shortly.";

  useEffect(() => {
    if (
      !refreshRequested ||
      !refreshAccepted.current ||
      !refreshObservedActive ||
      weeklyStatus !== "waiting" ||
      refreshInvalidated.current
    ) {
      return;
    }
    refreshInvalidated.current = true;
    queryClient.invalidateQueries({ queryKey: ["weekly"] });
    queryClient.invalidateQueries({ queryKey: ["upcoming"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  }, [queryClient, refreshObservedActive, refreshRequested, weeklyStatus]);

  const setView = (view: ReleasesView) => {
    const next = new URLSearchParams(searchParams);
    next.set("view", view);
    setSearchParams(next);
  };

  const goToWeek = (target: WeekRef | null) => {
    const next = new URLSearchParams(searchParams);
    if (target) {
      next.set("week", target.week);
      next.set("year", target.year);
    } else {
      next.delete("week");
      next.delete("year");
    }
    setSearchParams(next);
  };

  const handleWeeklyRefresh = async () => {
    try {
      const result = await weeklyRefresh.mutateAsync();
      if (result.state === "paused" || (!result.accepted && result.error)) {
        addToast({
          type: "error",
          message:
            result.error ||
            "Weekly refresh is paused. Resume it in Settings, then retry.",
        });
        return;
      }
      refreshAccepted.current = result.accepted;
      refreshInvalidated.current = false;
      setRefreshObservedActive(
        result.state === "queued" || result.state === "running",
      );
      setRefreshRequested(true);
      addToast({
        type: "info",
        message:
          result.message ||
          (result.state === "running"
            ? "Release refresh is already running."
            : "Release refresh queued."),
      });
    } catch (error) {
      addToast({
        type: "error",
        message: `Unable to refresh releases: ${error instanceof Error ? error.message : "Unknown error"}`,
      });
    }
  };

  return (
    <div className="page-transition flex h-full min-h-0 flex-col">
      <PageHeader
        title="Releases"
        meta={
          currentView === "mine"
            ? "New issues and chapters from series you follow, week by week"
            : "Everything out across publishers, from your weekly pull source"
        }
        actions={
          <div className="flex items-center gap-2">
            <WeekBar week={week} onNavigate={goToWeek} />
            <Button
              type="button"
              variant="outline"
              size="toolbar"
              onClick={() => void handleWeeklyRefresh()}
              disabled={
                weeklyRefresh.isPending ||
                weeklyStatus === "running" ||
                weeklyStatus === "queued"
              }
            >
              <RefreshCw
                className={
                  weeklyRefresh.isPending ||
                  weeklyStatus === "running" ||
                  weeklyStatus === "queued"
                    ? "animate-spin"
                    : ""
                }
              />
              <span className="max-md:sr-only">
                {weeklyStatus === "running"
                  ? "Refreshing…"
                  : weeklyStatus === "queued"
                    ? "Queued…"
                    : "Refresh releases"}
              </span>
            </Button>
          </div>
        }
      />

      {refreshMessage && (
        <div
          role={weeklyStatus === "error" ? "alert" : "status"}
          aria-live={weeklyStatus === "error" ? "assertive" : "polite"}
          className="shrink-0 px-8 pb-2 text-[13px]"
          style={{
            color:
              weeklyStatus === "error"
                ? "var(--status-error)"
                : weeklyStatus === "running"
                  ? "var(--status-active)"
                  : "var(--muted-foreground)",
          }}
        >
          {refreshMessage}
          {weeklyStatus === "error" &&
            !/Walksoftly is unreachable|down upstream/i.test(
              weeklyJob?.last_error || "",
            ) &&
            " Retry after fixing the pull source connection."}
        </div>
      )}

      <TabRow>
        <Tab
          active={currentView === "mine"}
          label="Mine"
          meta={mine.data?.length}
          onClick={() => setView("mine")}
        />
        <Tab
          active={currentView === "all"}
          label="Industry"
          meta={week?.rows.length}
          onClick={() => setView("all")}
        />
      </TabRow>

      <div className="flex-1 min-h-0 flex flex-col">
        {currentView === "mine" ? (
          <MyReleasesView
            issues={mine.data ?? []}
            isLoading={mine.isLoading}
            isFetching={mine.isFetching}
            error={mine.error}
            refetch={mine.refetch}
            start={week?.start}
          />
        ) : (
          <IndustryReleasesView selectedWeek={selectedWeek} />
        )}
      </div>
    </div>
  );
}
