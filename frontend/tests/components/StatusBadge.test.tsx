import { describe, expect, it } from "vitest";
import { render } from "../test-utils";
import StatusBadge from "@/components/StatusBadge";
import { STATUS_TONE_KEYS, statusTone } from "@/lib/statusTone";
import {
  ISSUE_DISPLAY_STATE_VALUES,
  SERIES_STATUS_VALUES,
} from "@/types/states.generated";

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

  it("keeps the raw provider label when mapping Downloading onto active", () => {
    const tone = statusTone("Downloading");
    expect(tone?.token).toBe("var(--status-active)");
    expect(tone?.label).toBe("Downloading");
    const { container } = render(
      <StatusBadge status="Downloading" variant="dot" />,
    );
    expect(container.textContent).toContain("Downloading");
    expect(container.textContent).not.toContain("Active");
  });

  it("keeps Unknown on the paused token", () => {
    expect(statusTone("Unknown")?.token).toBe("var(--status-paused)");
  });

  it("gives every registered issue and series state its own tone", () => {
    for (const state of [
      ...ISSUE_DISPLAY_STATE_VALUES,
      ...SERIES_STATUS_VALUES,
    ]) {
      // "custom" is the fallback for a word the vocabulary does not know.
      expect(statusTone(state)?.key, state).toBe(state.toLowerCase());
      expect(statusTone(state.toLowerCase())?.key, state).toBe(
        state.toLowerCase(),
      );
    }
  });

  it("labels a chapter covered by an owned volume from the vocabulary", () => {
    const tone = statusTone("Covered");
    expect(tone?.key).toBe("covered");
    expect(tone?.label).toBe("Covered");
    expect(tone?.token).toBe("var(--muted-foreground)");
  });

  it("capitalizes a series in Error as the series table sends it", () => {
    const { container } = render(<StatusBadge variant="dot" status="error" />);
    expect(container.textContent).toBe("Error");
    expect(statusTone("error")?.token).toBe("var(--status-error)");
  });

  it("does not invent a description tooltip", () => {
    const { container } = render(<StatusBadge status="Wanted" variant="dot" />);
    expect(container.querySelector("[title]")).toBeNull();
  });
});
