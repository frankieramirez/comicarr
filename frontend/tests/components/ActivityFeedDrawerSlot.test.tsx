import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ActivityFeedDrawerSlot } from "@/components/layout/Layout";

const counters = vi.hoisted(() => ({ moduleLoads: 0, activityRenders: 0 }));

vi.mock("@/components/ai/ActivityFeedDrawer", () => {
  counters.moduleLoads += 1;
  return {
    ActivityFeedDrawer: ({
      onOpenChange,
    }: {
      onOpenChange: (open: boolean) => void;
    }) => {
      counters.activityRenders += 1;
      return (
        <div role="dialog">
          AI activity
          <button type="button" onClick={() => onOpenChange(false)}>
            Close
          </button>
        </div>
      );
    },
  };
});

describe("ActivityFeedDrawerSlot", () => {
  it("defers activity loading until open and supports close/reopen", async () => {
    const onOpenChange = vi.fn();
    const view = render(
      <ActivityFeedDrawerSlot open={false} onOpenChange={onOpenChange} />,
    );

    expect(counters.moduleLoads).toBe(0);
    expect(counters.activityRenders).toBe(0);

    view.rerender(<ActivityFeedDrawerSlot open onOpenChange={onOpenChange} />);
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(counters.moduleLoads).toBe(1);
    expect(counters.activityRenders).toBe(1);

    view.rerender(
      <ActivityFeedDrawerSlot open={false} onOpenChange={onOpenChange} />,
    );
    expect(screen.queryByRole("dialog")).toBeNull();

    view.rerender(<ActivityFeedDrawerSlot open onOpenChange={onOpenChange} />);
    await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy());
    expect(counters.moduleLoads).toBe(1);
    expect(counters.activityRenders).toBe(2);
  });
});
