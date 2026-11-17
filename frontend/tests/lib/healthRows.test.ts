import { describe, expect, it } from "vitest";
import { jobRows } from "@/lib/healthRows";

const base = {
  id: "search",
  name: "Auto-Search",
  next_run_time: "2026-11-17 22:00:00+00:00",
  state: "waiting",
  dispatch: { last_attempt: 1_763_400_000 },
};

describe("jobRows", () => {
  it("shows a partly failed run as a warning, not a success (#1506)", () => {
    const [row] = jobRows([
      {
        ...base,
        result: "1 grabbed of 3 searched, 2 failed",
        result_partial: true,
      },
    ]);
    expect(row.tone).toBe("warn");
    expect(row.result).toBe("1 grabbed of 3 searched, 2 failed");
  });

  it("keeps a clean run green", () => {
    const [row] = jobRows([{ ...base, result: "1 grabbed of 1 searched" }]);
    expect(row.tone).toBe("ok");
  });

  it("does not claim success when a job reports nothing", () => {
    const [row] = jobRows([{ ...base, result: null }]);
    expect(row.result).toBe("Finished, nothing to report");
  });
});
