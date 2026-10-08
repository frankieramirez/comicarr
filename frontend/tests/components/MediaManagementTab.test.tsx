import { describe, expect, it, vi } from "vitest";
import { render, screen } from "../test-utils";
import { MediaManagementTab } from "@/components/settings/MediaManagementTab";

describe("MediaManagementTab import file operation", () => {
  it("defaults Import file operation to Same as downloads", () => {
    render(<MediaManagementTab config={{}} formData={{}} onChange={vi.fn()} />);

    const trigger = screen.getByRole("combobox", {
      name: "Import file operation",
    });
    expect(trigger.textContent).toContain("Same as downloads");
  });

  it("shows a stored import mode instead of the inherit label", () => {
    render(
      <MediaManagementTab
        config={{}}
        formData={{ imp_file_opts: "move" }}
        onChange={vi.fn()}
      />,
    );

    const trigger = screen.getByRole("combobox", {
      name: "Import file operation",
    });
    expect(trigger.textContent).toContain("Move");
    expect(trigger.textContent).not.toContain("Same as downloads");
  });
});
