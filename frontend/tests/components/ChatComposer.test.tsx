import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen } from "../test-utils";
import { ChatComposer } from "@/components/ai/ChatComposer";

describe("ChatComposer", () => {
  beforeEach(() => {
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:preview"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
  });

  it("accepts image attachments and rejects unsupported files", async () => {
    const onImagesChange = vi.fn();
    const onValidationError = vi.fn();
    const user = userEvent.setup();
    render(
      <ChatComposer
        value=""
        images={[]}
        isSending={false}
        onChange={vi.fn()}
        onImagesChange={onImagesChange}
        onSubmit={vi.fn()}
        onStop={vi.fn()}
        onValidationError={onValidationError}
      />,
    );

    const picker =
      document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(picker).toBeTruthy();
    await user.upload(
      picker as HTMLInputElement,
      new File(["cover"], "cover.png", { type: "image/png" }),
    );
    expect(onImagesChange).toHaveBeenCalledOnce();

    fireEvent.change(picker as HTMLInputElement, {
      target: {
        files: [new File(["notes"], "notes.txt", { type: "text/plain" })],
      },
    });
    expect(onValidationError).toHaveBeenCalledWith(
      "Choose JPEG, PNG, or WebP images.",
    );
    expect(screen.getByRole("button", { name: "Attach images" })).toBeTruthy();
  });
});
