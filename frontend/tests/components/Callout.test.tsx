import { describe, expect, it } from "vitest";
import { render, screen } from "../test-utils";
import { Callout, type CalloutTone } from "@/components/ui/callout";

const tones: CalloutTone[] = ["error", "warning", "success", "info"];

describe("Callout", () => {
  it.each(tones)(
    "renders tone %s with the matching status fill class",
    (tone) => {
      const { container } = render(<Callout tone={tone}>{tone}</Callout>);
      const el = container.firstElementChild as HTMLElement;
      const fill: Record<CalloutTone, string> = {
        error: "bg-[var(--status-error-bg)]",
        warning: "bg-[var(--status-paused-bg)]",
        success: "bg-[var(--status-active-bg)]",
        info: "bg-[var(--status-wanted-bg)]",
      };
      expect(el.className).toContain(fill[tone]);
      expect(el.className).toContain("_30%");
    },
  );

  it("exposes role=alert for error and warning", () => {
    const { rerender } = render(<Callout tone="error">Broken</Callout>);
    expect(screen.getByRole("alert").textContent).toBe("Broken");
    rerender(<Callout tone="warning">Heads up</Callout>);
    expect(screen.getByRole("alert").textContent).toBe("Heads up");
    rerender(<Callout tone="info">Note</Callout>);
    expect(screen.getByRole("status").textContent).toBe("Note");
  });

  it("keeps body copy on foreground and tone on the icon", () => {
    const { container } = render(<Callout tone="warning">Heads up</Callout>);
    const el = container.firstElementChild as HTMLElement;
    expect(el.className).toContain("text-foreground");
    expect(el.className).toContain("[&_svg]:text-[var(--status-paused)]");
    expect(el.className.split(/\s+/)).not.toContain(
      "text-[var(--status-paused)]",
    );
  });
});
