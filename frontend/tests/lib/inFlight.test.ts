import { describe, it, expect } from "vitest";
import { inFlightView } from "@/lib/inFlight";

describe("inFlightView", () => {
  it("says nothing is in flight rather than reporting a bare zero", () => {
    const view = inFlightView({ inFlight: 0, recoveryPending: 0 });

    expect(view.text).toBe("nothing in flight");
    expect(view.busy).toBe(false);
  });

  it("reports the count on its own when nothing was recovered", () => {
    const view = inFlightView({ inFlight: 12, recoveryPending: 0 });

    expect(view.text).toBe("12 in flight");
    expect(view.busy).toBe(true);
  });

  it("qualifies the count with restart recoveries instead of summing them", () => {
    // 12 is the total; the 3 are part of it, so 15 must never appear.
    expect(inFlightView({ inFlight: 12, recoveryPending: 3 }).text).toBe(
      "12 in flight (3 recovered from a restart)",
    );
  });

  it("treats a missing recovery figure as no qualifier", () => {
    expect(inFlightView({ inFlight: 4 }).text).toBe("4 in flight");
  });

  it("keeps the qualifier a subset of the total", () => {
    expect(inFlightView({ inFlight: 2, recoveryPending: 5 }).text).toBe(
      "2 in flight (2 recovered from a restart)",
    );
  });
});
