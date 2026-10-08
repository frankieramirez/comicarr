import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider, useToast } from "@/components/ui/toast";

function ErrorToastTrigger() {
  const { addToast } = useToast();
  return (
    <button
      type="button"
      onClick={() => addToast({ type: "error", message: "Logout failed" })}
    >
      Show error
    </button>
  );
}

function SuccessToastTrigger() {
  const { addToast } = useToast();
  return (
    <button
      type="button"
      onClick={() =>
        addToast({ type: "success", message: "Saved", duration: 5_000 })
      }
    >
      Show success
    </button>
  );
}

describe("Toast accessibility", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("announces error feedback and labels its dismiss control", async () => {
    render(
      <ToastProvider>
        <ErrorToastTrigger />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Show error" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Logout failed");
    expect(
      screen.getByRole("button", { name: "Dismiss notification" }),
    ).toBeTruthy();
  });

  it("announces success toasts from a persistent polite live region", async () => {
    render(
      <ToastProvider>
        <SuccessToastTrigger />
      </ToastProvider>,
    );

    const liveRegion = screen.getByRole("status");
    expect(liveRegion.getAttribute("aria-live")).toBe("polite");
    expect(liveRegion.textContent).not.toContain("Saved");

    fireEvent.click(screen.getByRole("button", { name: "Show success" }));

    expect(await screen.findByText("Saved")).toBeTruthy();
    expect(liveRegion.textContent).toContain("Saved");
  });

  it("pauses auto-dismiss while the toast is hovered or focused", () => {
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <SuccessToastTrigger />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Show success" }));
    const toast = screen.getByTestId("toast");

    act(() => {
      vi.advanceTimersByTime(4_000);
    });
    expect(screen.getByText("Saved")).toBeTruthy();

    fireEvent.mouseEnter(toast);
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(screen.getByText("Saved")).toBeTruthy();

    fireEvent.mouseLeave(toast);
    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    expect(screen.queryByText("Saved")).toBeNull();
  });
});
