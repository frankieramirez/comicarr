import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WhatsNewGate } from "@/components/layout/Layout";

type ModalModule = typeof import("@/components/whats-new/WhatsNewModal").default;

const version = vi.hoisted(() => ({
  status: "success" as "pending" | "error" | "success",
  data: undefined as
    | { pending_whats_new: { from: string; to: string } | null }
    | undefined,
}));

vi.mock("@/hooks/useVersion", () => ({
  useVersionInfo: () => ({ status: version.status, data: version.data }),
}));

const StubModal: ModalModule = function StubModal() {
  const [open, setOpen] = useState(true);
  if (!open) return null;
  return (
    <div role="dialog">
      Comicarr updated
      <button type="button" onClick={() => setOpen(false)}>
        Close
      </button>
    </div>
  );
};

function setPending(pending: { from: string; to: string } | null) {
  version.status = "success";
  version.data = { pending_whats_new: pending };
}

describe("WhatsNewGate", () => {
  beforeEach(() => {
    setPending(null);
  });

  it("does not import the modal until an upgrade is pending", async () => {
    const load = vi.fn(() => Promise.resolve(StubModal));
    const view = render(<WhatsNewGate load={load} />);
    expect(load).not.toHaveBeenCalled();

    setPending({ from: "0.38.6", to: "0.38.7" });
    view.rerender(<WhatsNewGate load={load} />);
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("renders nothing when the optional chunk fails to load", async () => {
    const load = vi
      .fn<() => Promise<ModalModule>>()
      .mockRejectedValue(new Error("missing chunk"));
    setPending({ from: "0.38.6", to: "0.38.7" });
    const view = render(<WhatsNewGate load={load} />);

    await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
    expect(view.container.innerHTML).toBe("");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("keeps a closed modal closed across a failed version poll", async () => {
    const load = vi.fn(() => Promise.resolve(StubModal));
    const user = userEvent.setup();
    setPending({ from: "0.38.6", to: "0.38.7" });
    const view = render(<WhatsNewGate load={load} />);

    expect(await screen.findByRole("dialog")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    version.status = "error";
    view.rerender(<WhatsNewGate load={load} />);
    expect(screen.queryByRole("dialog")).toBeNull();

    version.status = "success";
    view.rerender(<WhatsNewGate load={load} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(load).toHaveBeenCalledTimes(1);
  });
});
