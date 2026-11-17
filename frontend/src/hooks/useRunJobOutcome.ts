// Copyright (C) 2026 Comicarr contributors

/**
 * Run a scheduled job and say how it went (#1493).
 *
 * The run endpoint only answers "accepted": the job itself runs on the
 * scheduler afterwards. So after an accepted run this watches the job's row
 * until its last run moves past the one it had before, then reports that
 * run's result. While it waits the jobs list is re-read every two seconds
 * instead of every fifteen, for at most five minutes.
 */

import { ph, t } from "@lingui/core/macro";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useToast } from "@/components/ui/toast";
import { useRunJob } from "@/hooks/useAcquisitionHealth";
import { getErrorMessage } from "@/lib/api";
import type { JobRow } from "@/lib/healthRows";

const WATCH_POLL_MS = 2_000;
const WATCH_LIMIT_MS = 5 * 60_000;

interface Watch {
  /** The job's last run when Run now was pressed, as epoch ms. */
  lastRunBefore: number | null;
  token: number;
}

export function useRunJobOutcome(job: JobRow) {
  const run = useRunJob();
  const queryClient = useQueryClient();
  const { addToast } = useToast();
  const [watch, setWatch] = useState<Watch | null>(null);
  const reported = useRef<number | null>(null);

  const lastRun = job.lastRun?.getTime() ?? null;
  const finished =
    watch !== null &&
    !job.busy &&
    lastRun !== null &&
    lastRun !== watch.lastRunBefore;
  const waiting = watch !== null && !finished;

  useEffect(() => {
    if (!waiting) return;
    const started = Date.now();
    const timer = setInterval(() => {
      if (Date.now() - started > WATCH_LIMIT_MS) {
        clearInterval(timer);
        return;
      }
      void queryClient.invalidateQueries({ queryKey: ["system", "jobs"] });
    }, WATCH_POLL_MS);
    return () => clearInterval(timer);
  }, [waiting, queryClient]);

  useEffect(() => {
    if (!finished || !watch || reported.current === watch.token) return;
    reported.current = watch.token;
    addToast(
      job.failing
        ? {
            type: "error",
            message: t`${ph({ label: job.label })} failed: ${ph({ result: job.result })}`,
          }
        : {
            type: "success",
            message: t`${ph({ label: job.label })} finished: ${ph({ result: job.result })}`,
          },
    );
  }, [finished, watch, job, addToast]);

  const start = async () => {
    const lastRunBefore = lastRun;
    try {
      const result = await run.mutateAsync(job.id);
      if (!result.accepted) {
        addToast({
          type: "error",
          message: result.error || t`${ph({ label: job.label })} didn't start.`,
        });
        return;
      }
      setWatch({ lastRunBefore, token: Date.now() });
    } catch (err) {
      addToast({ type: "error", message: getErrorMessage(err) });
    }
  };

  return {
    start,
    /** Started and not finished yet, so the button can say so. */
    running: run.isPending || waiting,
  };
}
