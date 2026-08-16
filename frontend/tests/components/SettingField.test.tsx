import { describe, expect, it, vi } from "vitest";
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
