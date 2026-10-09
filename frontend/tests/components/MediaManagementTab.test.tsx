import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen } from "../test-utils";
import { MediaManagementTab } from "@/components/settings/MediaManagementTab";

function importFileOperation() {
  return screen.getByRole("combobox", { name: "Import file operation" });
}

describe("MediaManagementTab import file operation", () => {
  it("defaults Import file operation to Same as downloads", () => {
    render(<MediaManagementTab config={{}} formData={{}} onChange={vi.fn()} />);

    expect(importFileOperation().textContent).toContain("Same as downloads");
  });

  it("treats the Mylar-era None string as Same as downloads", () => {
    render(
      <MediaManagementTab
        config={{}}
        formData={{ imp_file_opts: "None" }}
        onChange={vi.fn()}
      />,
    );

    expect(importFileOperation().textContent).toContain("Same as downloads");
  });

  it("shows a stored import mode instead of the inherit label", () => {
    render(
      <MediaManagementTab
        config={{}}
        formData={{ imp_file_opts: "move" }}
        onChange={vi.fn()}
      />,
    );

    expect(importFileOperation().textContent).toContain("Move");
    expect(importFileOperation().textContent).not.toContain(
      "Same as downloads",
    );
  });

  it("matches a padded or mixed-case stored value to the option", () => {
    render(
      <MediaManagementTab
        config={{}}
        formData={{ imp_file_opts: " Copy " }}
        onChange={vi.fn()}
      />,
    );

    expect(importFileOperation().textContent).toContain("Copy");
    expect(importFileOperation().textContent).not.toContain(
      "Same as downloads",
    );
  });

  it("treats whitespace-only values as Same as downloads", () => {
    render(
      <MediaManagementTab
        config={{}}
        formData={{ imp_file_opts: "   " }}
        onChange={vi.fn()}
      />,
    );

    expect(importFileOperation().textContent).toContain("Same as downloads");
  });

  it("saves a chosen mode as its own value", async () => {
    const onChange = vi.fn();
    render(
      <MediaManagementTab config={{}} formData={{}} onChange={onChange} />,
    );

    await userEvent.click(importFileOperation());
    await userEvent.click(await screen.findByRole("option", { name: "Move" }));

    expect(onChange).toHaveBeenCalledWith("imp_file_opts", "move");
  });

  it("saves Same as downloads as an empty value, never the UI sentinel", async () => {
    const onChange = vi.fn();
    render(
      <MediaManagementTab
        config={{}}
        formData={{ imp_file_opts: "move" }}
        onChange={onChange}
      />,
    );

    await userEvent.click(importFileOperation());
    await userEvent.click(
      await screen.findByRole("option", { name: "Same as downloads" }),
    );

    expect(onChange).toHaveBeenCalledWith("imp_file_opts", "");
    expect(onChange).not.toHaveBeenCalledWith("imp_file_opts", "file_opts");
  });

  it("labels the IMP_MOVE checkbox as placement, not as a move", () => {
    render(<MediaManagementTab config={{}} formData={{}} onChange={vi.fn()} />);

    expect(
      screen.getByRole("checkbox", {
        name: /^Place imported files in the library/,
      }),
    ).toBeTruthy();
    expect(screen.queryByText("Move files on import")).toBeNull();
  });

  it("saves an auto-import confidence of 0 as 0", () => {
    const onChange = vi.fn();
    render(
      <MediaManagementTab
        config={{}}
        formData={{ auto_import_confidence: 80 }}
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByLabelText("Auto-import confidence"), {
      target: { value: "0" },
    });

    expect(onChange).toHaveBeenCalledWith("auto_import_confidence", 0);
  });
});
