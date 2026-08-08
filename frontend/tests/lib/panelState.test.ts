import { describe, expect, it } from "vitest";
import { panelState } from "@/lib/panelState";

describe("panelState", () => {
  it("reports a failed source as unavailable, never as empty", () => {
    expect(
      panelState({ isPending: false, isError: true }, true),
    ).toBe("unavailable");
  });

  it("prefers unavailable over loading while a failed query refetches", () => {
    expect(panelState({ isPending: true, isError: true }, false)).toBe(
      "unavailable",
    );
  });

  it("is loading until the query answers", () => {
    expect(panelState({ isPending: true, isError: false }, true)).toBe(
      "loading",
    );
  });

  it("is empty only once an answer says so", () => {
    expect(panelState({ isPending: false, isError: false }, true)).toBe("empty");
  });

  it("has content when the answer is non-empty", () => {
    expect(panelState({ isPending: false, isError: false }, false)).toBe(
      "content",
    );
  });
});
