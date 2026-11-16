import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
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
        label={t`Timeline`}
        onClick={() => go("timeline")}
      />
      <Tab
        active={active === "in_flight"}
        label={t`In flight`}
        onClick={() => go("in_flight")}
      />
      <Tab
        active={active === "queue"}
        label={t`Direct downloads`}
        onClick={() => go("queue")}
      />
      <Tab
        active={active === "history"}
        label={t`History`}
        onClick={() => go("history")}
      />
      <Tab
        active={active === "attention"}
        label={t`Needs you`}
        meta={
          attention > 0 ? (
            <span style={{ color: "var(--status-error)" }}>{attention}</span>
          ) : undefined
        }
        onClick={() => navigate("/activity/attention")}
      />
      <Tab
        active={active === "health"}
        label={t`Health`}
        meta={
          failingJobs > 0 ? (
            <span style={{ color: "var(--status-error)" }}>
              <Trans>{failingJobs} failing</Trans>
            </span>
          ) : undefined
        }
        onClick={() => go("health")}
      />
    </TabRow>
  );
}
