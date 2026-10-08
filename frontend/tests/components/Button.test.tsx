import { describe, expect, it } from "vitest";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

describe("buttonVariants", () => {
  it("keeps the shared focus ring and disabled pointer-events on compact and toolbar", () => {
    for (const size of ["compact", "toolbar"] as const) {
      const classes = buttonVariants({ size });
      expect(classes).toContain("focus-visible:ring-1");
      expect(classes).toContain("focus-visible:ring-ring");
      expect(classes).toContain("disabled:pointer-events-none");
      expect(classes).toContain("disabled:opacity-50");
      expect(classes).toContain("rounded-control");
      expect(classes).toContain("text-[12px]");
    }
  });

  it("sizes compact to h-7 and toolbar to h-8", () => {
    expect(buttonVariants({ size: "compact" })).toContain("h-7");
    expect(buttonVariants({ size: "compact" })).toContain("px-2.5");
    expect(buttonVariants({ size: "toolbar" })).toContain("h-8");
    expect(buttonVariants({ size: "toolbar" })).toContain("px-3");
  });

  it("keeps compact icons at 12px and toolbar icons at 14px", () => {
    expect(cn(buttonVariants({ size: "compact" }))).toContain("[&_svg]:size-3");
    expect(cn(buttonVariants({ size: "compact" }))).not.toContain(
      "[&_svg]:size-4",
    );
    expect(cn(buttonVariants({ size: "toolbar" }))).toContain(
      "[&_svg]:size-3.5",
    );
    expect(cn(buttonVariants({ size: "toolbar" }))).not.toContain(
      "[&_svg]:size-4",
    );
  });

  it("keeps dense outline transparent with a --border edge", () => {
    for (const size of ["compact", "toolbar"] as const) {
      const classes = cn(buttonVariants({ variant: "outline", size }));
      expect(classes).toContain("border-border");
      expect(classes).not.toContain("border-input");
      expect(classes).toContain("bg-transparent");
      expect(classes).not.toContain("bg-background");
      expect(classes).toContain("shadow-none");
      expect(classes).not.toContain("shadow-sm");
      expect(classes).toContain("hover:bg-secondary/50");
    }
  });

  it("gives destructive buttons a registered contrasting foreground", () => {
    const classes = buttonVariants({ variant: "destructive" });
    expect(classes).toContain("bg-destructive");
    expect(classes).toContain("text-destructive-foreground");
  });

  it("adds the mono modifier without dropping the focus ring", () => {
    const classes = buttonVariants({ size: "compact", mono: true });
    expect(classes).toContain("font-mono");
    expect(classes).toContain("uppercase");
    expect(classes).toContain("focus-visible:ring-1");
    expect(classes).toContain("disabled:pointer-events-none");
  });
});
