import { describe, it, expect } from "vitest";
import { inFlightView } from "@/lib/inFlight";

describe("inFlightView", () => {
  it("says nothing is in flight rather than reporting a bare zero", () => {
    const view = inFlightView({ inFlight: 0, recoveryPending: 0 });

    expect(view.text).toBe("nothing in flight");
    expect(view.count).toBe(0);
    expect(view.busy).toBe(false);
  });

  it("reports the count on its own when nothing was recovered", () => {
    const view = inFlightView({ inFlight: 12, recoveryPending: 0 });

    expect(view.text).toBe("12 in flight");
    expect(view.recovered).toBe(0);
    expect(view.busy).toBe(true);
  });

  it("qualifies the count with restart recoveries instead of summing them", () => {
    const view = inFlightView({ inFlight: 12, recoveryPending: 3 });

    // 12 is the total; the 3 are *part of* it, so 15 must never appear.
    expect(view.text).toBe("12 in flight (3 recovered from a restart)");
    expect(view.count).toBe(12);
    expect(view.recovered).toBe(3);
  });

  it("treats a missing recovery figure as no qualifier", () => {
    expect(inFlightView({ inFlight: 4 }).text).toBe("4 in flight");
  });

  it("keeps the qualifier a subset of the total", () => {
    // `recovery_pending` is defined as a subset of `in_flight`; a payload that
    // contradicts that must not make the parenthetical exceed the total.
    const view = inFlightView({ inFlight: 2, recoveryPending: 5 });

    expect(view.text).toBe("2 in flight (2 recovered from a restart)");
    expect(view.count).toBe(2);
  });

  it("refuses counts it cannot stand behind", () => {
    expect(inFlightView({ inFlight: -3 }).text).toBe("nothing in flight");
    expect(inFlightView({ inFlight: Number.NaN }).busy).toBe(false);
    expect(inFlightView({ inFlight: 3.7, recoveryPending: 1.9 }).text).toBe(
      "3 in flight (1 recovered from a restart)",
    );
  });
});
