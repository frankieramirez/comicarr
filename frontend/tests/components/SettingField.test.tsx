import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen } from "../test-utils";
import {
  SettingField,
  labelForSelectValue,
} from "@/components/settings/SettingField";

const NZB_CLIENT_OPTIONS = [
  { value: "3", label: "Disabled" },
  { value: "0", label: "SABnzbd" },
  { value: "1", label: "NZBGet" },
  { value: "2", label: "Blackhole" },
];

describe("labelForSelectValue", () => {
  it("maps a coded stored value to its option label", () => {
    expect(labelForSelectValue(NZB_CLIENT_OPTIONS, "3")).toBe("Disabled");
    expect(labelForSelectValue(NZB_CLIENT_OPTIONS, 0)).toBe("SABnzbd");
    expect(labelForSelectValue(NZB_CLIENT_OPTIONS, "missing")).toBeUndefined();
  });
});

describe("SettingField select", () => {
  it("shows the option label on first paint before the popup is opened", () => {
    render(
      <SettingField
        label="NZB client"
        type="select"
        value="3"
        options={NZB_CLIENT_OPTIONS}
        onChange={vi.fn()}
      />,
    );

    const trigger = screen.getByRole("combobox", { name: "NZB client" });
    expect(trigger.textContent).toContain("Disabled");
    expect(trigger.textContent).not.toMatch(/(^|[^A-Za-z])3([^0-9]|$)/);
  });
});

describe("SettingField checkbox", () => {
  it("shows a visible offset ring on a checked toggle when focused", async () => {
    document.documentElement.classList.add("dark");
    document.documentElement.style.setProperty("--background", "#111111");
    document.documentElement.style.setProperty("--ring", "#ff6a1f");
    const user = userEvent.setup();
    render(
      <SettingField
        label="Enable notifications"
        type="checkbox"
        checked={true}
        onChange={vi.fn()}
      />,
    );

    await user.tab();
    const input = screen.getByRole("checkbox", {
      name: "Enable notifications",
    });
    expect(document.activeElement).toBe(input);
    const visual = input.nextElementSibling as HTMLElement;
    expect(visual.className).toMatch(/peer-focus-visible:ring-2/);
    expect(visual.className).toMatch(/peer-focus-visible:ring-offset-2/);
    expect(visual.className).toMatch(
      /peer-focus-visible:ring-offset-background/,
    );
    const shadow = getComputedStyle(visual).boxShadow;
    expect(shadow).not.toBe("none");
    expect(shadow).toMatch(/0px 0px 0px 2px|0 0 0 2px/);
    expect(shadow).toMatch(/0px 0px 0px 4px|0 0 0 4px/);
    document.documentElement.classList.remove("dark");
    document.documentElement.style.removeProperty("--background");
    document.documentElement.style.removeProperty("--ring");
  });
});

describe("SettingField textarea", () => {
  it("edits a multi-line value such as one path per line", async () => {
    const onChange = vi.fn();
    render(
      <SettingField
        label="Additional library roots"
        type="textarea"
        value={"/comics/Magazines\n/comics/Kids"}
        onChange={onChange}
      />,
    );

    const field = screen.getByRole("textbox", {
      name: "Additional library roots",
    }) as HTMLTextAreaElement;
    expect(field.tagName).toBe("TEXTAREA");
    expect(field.value).toBe("/comics/Magazines\n/comics/Kids");
  });
});
