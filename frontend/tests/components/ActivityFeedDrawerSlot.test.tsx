import { describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ActivityFeedDrawerSlot } from "@/components/layout/Layout";

type DrawerProps = { open: boolean; onOpenChange: (open: boolean) => void };
type DrawerModule = typeof import("@/components/ai/ActivityFeedDrawer").ActivityFeedDrawer;

/** Mirrors a Sheet: mounted while closed, but renders no dialog. */
function makeStubDrawer(seenOpen: boolean[]): DrawerModule {
  return function StubDrawer({ open, onOpenChange }: DrawerProps) {
    seenOpen.push(open);
    if (!open) return null;
    return (
      <div role="dialog">
        AI activity
        <button type="button" onClick={() => onOpenChange(false)}>
          Close
        </button>
      </div>
    );
  };
}

describe("ActivityFeedDrawerSlot", () => {
  it("defers loading until open, then keeps the drawer mounted with the real open prop", async () => {
    const seenOpen: boolean[] = [];
    const load = vi.fn(() => Promise.resolve(makeStubDrawer(seenOpen)));
    const onOpenChange = vi.fn();
    const view = render(
      <ActivityFeedDrawerSlot
        open={false}
        onOpenChange={onOpenChange}
        load={load}
      />,
    );

    expect(load).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();

    view.rerender(
      <ActivityFeedDrawerSlot open onOpenChange={onOpenChange} load={load} />,
    );
    expect(screen.getByRole("status").textContent).toContain(
      "Loading AI activity",
    );
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(load).toHaveBeenCalledTimes(1);

    view.rerender(
      <ActivityFeedDrawerSlot
        open={false}
        onOpenChange={onOpenChange}
        load={load}
      />,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    // The loaded drawer stayed mounted and saw open=false, so the Sheet can
    // run its own close transition instead of being torn out of the tree.
    expect(seenOpen.at(-1)).toBe(false);

    view.rerender(
      <ActivityFeedDrawerSlot open onOpenChange={onOpenChange} load={load} />,
    );
    await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy());
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("shows a fallback when the chunk fails and retries on the next open", async () => {
    const load = vi
      .fn<() => Promise<DrawerModule>>()
      .mockRejectedValueOnce(new Error("missing chunk"))
      .mockResolvedValueOnce(makeStubDrawer([]));
    const onOpenChange = vi.fn();
    const user = userEvent.setup();
    const view = render(
      <ActivityFeedDrawerSlot open onOpenChange={onOpenChange} load={load} />,
    );

    expect(
      (await screen.findByText(/AI activity failed to load/)).textContent,
    ).toContain("Reload the page");
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);

    view.rerender(
      <ActivityFeedDrawerSlot
        open={false}
        onOpenChange={onOpenChange}
        load={load}
      />,
    );
    expect(screen.queryByText(/AI activity failed to load/)).toBeNull();

    view.rerender(
      <ActivityFeedDrawerSlot open onOpenChange={onOpenChange} load={load} />,
    );
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("ignores a module that resolves after the slot closed", async () => {
    let resolveModule: ((module: DrawerModule) => void) | undefined;
    const load = vi.fn(
      () =>
        new Promise<DrawerModule>((resolve) => {
          resolveModule = resolve;
        }),
    );
    const onOpenChange = vi.fn();
    const view = render(
      <ActivityFeedDrawerSlot open onOpenChange={onOpenChange} load={load} />,
    );
    expect(load).toHaveBeenCalledTimes(1);

    view.rerender(
      <ActivityFeedDrawerSlot
        open={false}
        onOpenChange={onOpenChange}
        load={load}
      />,
    );
    await act(async () => {
      resolveModule?.(makeStubDrawer([]));
    });
    expect(screen.queryByRole("dialog")).toBeNull();

    view.rerender(
      <ActivityFeedDrawerSlot open onOpenChange={onOpenChange} load={load} />,
    );
    expect(load).toHaveBeenCalledTimes(2);
    await act(async () => {
      resolveModule?.(makeStubDrawer([]));
    });
    expect(await screen.findByRole("dialog")).toBeTruthy();
  });
});
