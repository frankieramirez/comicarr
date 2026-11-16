import { ph, t } from "@lingui/core/macro";
import { errorText } from "@/lib/api";
import { useEffect, useState, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { useUpcoming } from "@/hooks/useQueue";
import { useQueryClient } from "@tanstack/react-query";
import PageHeader from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import {
  useScheduledJobs,
  useWeeklyPullList,
  useWeeklyRefresh,
} from "@/hooks/useWeekly";
import IndustryReleasesView from "@/components/releases/IndustryReleasesView";
import MyReleasesView from "@/components/releases/MyReleasesView";
import { withLibraryManga } from "@/components/releases/industryRows";
import WeekBar from "@/components/releases/WeekBar";
import ReleasesModeBar from "@/components/releases/ReleasesModeBar";
import {
  INDUSTRY_FORMATS,
  LIBRARY_FORMATS,
  libraryFormat,
  releasePrefs,
  type ReleaseFormat,
} from "@/components/releases/releaseFormat";
import type { WeekRef } from "@/pages/weeklyReleaseRowKey";

function readWeek(params: URLSearchParams): WeekRef | null {
  const week = params.get("week");
  const year = params.get("year");
  return week && year ? { week, year } : null;
}

/**
 * Releases is one list (#1383): everything out this week, comics and
 * manga alike, with "Only my library" narrowing it to the library's own
 * series and what they need. `?view=mine` and `?view=all` still link
 * straight to either side.
 */
export default function ReleasesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const viewParam = searchParams.get("view");
  const libraryOnly =
    viewParam === "mine"
      ? true
      : viewParam === "all"
        ? false
        : releasePrefs.libraryOnly();
  const [format, setFormatState] = useState<ReleaseFormat>(() =>
    releasePrefs.format(),
  );
  const setFormat = (next: ReleaseFormat) => {
    releasePrefs.setFormat(next);
    setFormatState(next);
  };
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
      ? t`Refresh queued — it will start shortly.`
      : weeklyStatus === "running"
        ? t`Refreshing releases…`
        : weeklyStatus === "error"
          ? weeklyJob?.last_error ||
            t`Refresh failed. Check the pull source, then retry.`
          : weeklyStatus === "waiting" && refreshObservedActive
            ? t`Releases refreshed.`
            : t`Refresh queued — it will start shortly.`;

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

  const setLibraryOnly = (value: boolean) => {
    releasePrefs.setLibraryOnly(value);
    const next = new URLSearchParams(searchParams);
    next.set("view", value ? "mine" : "all");
    setSearchParams(next);
  };

  const modeBar = (counts?: Partial<Record<ReleaseFormat, number>>) => (
    <ReleasesModeBar
      formats={libraryOnly ? LIBRARY_FORMATS : INDUSTRY_FORMATS}
      format={libraryOnly ? libraryFormat(format) : format}
      onFormatChange={setFormat}
      counts={counts}
      libraryOnly={libraryOnly}
      onLibraryOnlyChange={setLibraryOnly}
    />
  );

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
            t`Weekly refresh is paused. Resume it in Settings, then retry.`,
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
            ? t`Release refresh is already running.`
            : t`Release refresh queued.`),
      });
    } catch (error) {
      addToast({
        type: "error",
        message: t`Unable to refresh releases: ${ph({ error: errorText(error) })}`,
      });
    }
  };

  return (
    <div className="page-transition flex h-full min-h-0 flex-col">
      <PageHeader
        title={t`Releases`}
        meta={
          libraryOnly
            ? t`New issues and chapters from series you follow, week by week`
            : t`Everything out this week: comics, manga, manhwa and manhua`
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
                  ? t`Refreshing…`
                  : weeklyStatus === "queued"
                    ? t`Queued…`
                    : t`Refresh releases`}
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
            ) && <> {t`Retry after fixing the pull source connection.`}</>}
        </div>
      )}

      <div className="flex-1 min-h-0 flex flex-col">
        {libraryOnly ? (
          <MyReleasesView
            modeBar={modeBar}
            format={libraryFormat(format)}
            issues={withLibraryManga(week, mine.data ?? [])}
            isLoading={mine.isLoading}
            isFetching={mine.isFetching}
            error={mine.error}
            refetch={mine.refetch}
            start={week?.start}
            pullUnavailable={week?.source === "unavailable"}
          />
        ) : (
          <IndustryReleasesView
            selectedWeek={selectedWeek}
            modeBar={modeBar}
            format={format}
            libraryIssues={mine.data ?? []}
          />
        )}
      </div>
    </div>
  );
}
