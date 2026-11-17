// Copyright (C) 2026 Comicarr contributors

/**
 * Problems that stop work for the whole library rather than one issue
 * (#1493): a setup gap that stops every search, a missing Comic Vine key, and
 * a scheduled job whose last run failed. Activity > Needs you lists them above
 * the issue-level problems.
 */

import { useJobsHealth, useSearchBlockers } from "@/hooks/useAcquisitionHealth";
import { useContentSources } from "@/hooks/useContentSources";
import { jobRows, type JobRow } from "@/lib/healthRows";
import type { SearchBlocker } from "@/lib/searchBlockers";

export interface SystemProblems {
  blockers: SearchBlocker[];
  keyMissing: boolean;
  failingJobs: JobRow[];
  count: number;
}

export function useSystemProblems(): SystemProblems {
  const { blockers } = useSearchBlockers();
  const jobs = useJobsHealth();
  const sources = useContentSources();
  const failingJobs = jobRows(jobs.data?.jobs ?? []).filter(
    (job) => job.failing,
  );
  const keyMissing =
    sources.isLoaded && sources.comicsEnabled && !sources.comicsConfigured;
  return {
    blockers,
    keyMissing,
    failingJobs,
    count: blockers.length + failingJobs.length + (keyMissing ? 1 : 0),
  };
}
