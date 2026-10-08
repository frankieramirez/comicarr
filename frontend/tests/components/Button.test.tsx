import { describe, expect, it } from "vitest";
import { buttonVariants } from "@/components/ui/button";

describe("buttonVariants", () => {
  it("keeps the shared focus ring and disabled pointer-events on compact and toolbar", () => {
    for (const size of ["compact", "toolbar"] as const) {
      const classes = buttonVariants({ size });
      expect(classes).toContain("focus-visible:ring-1");
      expect(classes).toContain("focus-visible:ring-ring");
      expect(classes).toContain("disabled:pointer-events-none");
      expect(classes).toContain("disabled:opacity-50");
      expect(classes).toContain("rounded-[5px]");
      expect(classes).toContain("text-[12px]");
    }
  });

  it("sizes compact to h-7 and toolbar to h-8", () => {
    expect(buttonVariants({ size: "compact" })).toContain("h-7");
    expect(buttonVariants({ size: "compact" })).toContain("px-2.5");
    expect(buttonVariants({ size: "toolbar" })).toContain("h-8");
    expect(buttonVariants({ size: "toolbar" })).toContain("px-3");
  });

  it("adds the mono modifier without dropping the focus ring", () => {
    const classes = buttonVariants({ size: "compact", mono: true });
    expect(classes).toContain("font-mono");
    expect(classes).toContain("uppercase");
    expect(classes).toContain("focus-visible:ring-1");
    expect(classes).toContain("disabled:pointer-events-none");
  });
});
