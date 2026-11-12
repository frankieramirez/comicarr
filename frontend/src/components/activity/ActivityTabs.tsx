import { useNavigate } from "react-router-dom";
import { Tab, TabRow } from "@/components/layout/PageHeader";
import { useActivityStatus } from "@/hooks/useActivityStatus";
import { useJobsHealth } from "@/hooks/useAcquisitionHealth";
import { jobRows } from "@/lib/healthRows";

export type ActivityTab =
  "timeline" | "in_flight" | "queue" | "history" | "health";

/**
 * The tab row Activity and its Needs you route share, so moving between the
 * timeline and the triage list reads as one page.
 */
export function ActivityTabs({
  active,
  onSelect,
}: {
  active: ActivityTab | "attention";
  onSelect?: (view: ActivityTab) => void;
}) {
  const navigate = useNavigate();
  const attention = useActivityStatus().data?.attention ?? 0;
  const failingJobs = jobRows(useJobsHealth().data?.jobs ?? []).filter(
    (job) => job.failing,
  ).length;
  const go = (view: ActivityTab) => {
    if (onSelect) {
      onSelect(view);
      return;
    }
    navigate(
      view === "timeline"
        ? "/activity"
        : view === "in_flight"
          ? "/activity?state=in_flight"
          : `/activity?view=${view}`,
    );
  };

  return (
    <TabRow>
      <Tab
        active={active === "timeline"}
        label="Timeline"
        onClick={() => go("timeline")}
      />
      <Tab
        active={active === "in_flight"}
        label="In flight"
        onClick={() => go("in_flight")}
      />
      <Tab
        active={active === "queue"}
        label="Direct downloads"
        onClick={() => go("queue")}
      />
      <Tab
        active={active === "history"}
        label="History"
        onClick={() => go("history")}
      />
      <Tab
        active={active === "attention"}
        label="Needs you"
        meta={
          attention > 0 ? (
            <span style={{ color: "var(--status-error)" }}>{attention}</span>
          ) : undefined
        }
        onClick={() => navigate("/activity/attention")}
      />
      <Tab
        active={active === "health"}
        label="Health"
        meta={
          failingJobs > 0 ? (
            <span style={{ color: "var(--status-error)" }}>
              {failingJobs} failing
            </span>
          ) : undefined
        }
        onClick={() => go("health")}
      />
    </TabRow>
  );
}
