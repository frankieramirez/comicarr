import { describe, expect, it } from "vitest";
import { render } from "../test-utils";
import StatusBadge from "@/components/StatusBadge";
import { STATUS_TONE_KEYS, statusTone } from "@/lib/statusTone";

describe("StatusBadge statusTone", () => {
  it("uses the same dot token for pill and dot variants", () => {
    for (const status of STATUS_TONE_KEYS) {
      const token = statusTone(status)?.token;
      expect(token).toBeTruthy();

      const pill = render(<StatusBadge status={status} />);
      const pillDot = pill.container.querySelector(
        '[data-testid="status-dot"]',
      );
      expect(pillDot?.getAttribute("style") ?? "").toContain(token!);
      pill.unmount();

      const dot = render(<StatusBadge status={status} variant="dot" />);
      const rowDot = dot.container.querySelector('[data-testid="status-dot"]');
      expect(rowDot?.getAttribute("style") ?? "").toContain(token!);
      dot.unmount();
    }
  });

  it("paints Wanted with --status-wanted on the dense variant", () => {
    const { container } = render(<StatusBadge status="Wanted" variant="dot" />);
    const style = container
      .querySelector('[data-testid="status-dot"]')
      ?.getAttribute("style");
    expect(style).toContain("var(--status-wanted)");
  });
});
