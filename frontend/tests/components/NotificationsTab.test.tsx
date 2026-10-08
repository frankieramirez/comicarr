import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen } from "../test-utils";
import { NotificationsTab } from "@/components/settings/NotificationsTab";
import type {
  ReadableConfig,
  SettingsFormData,
} from "@/types/config.generated";

describe("NotificationsTab duplicate labels", () => {
  it("toggles Discord notify-on-snatch when that label is clicked", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const formData = {
      telegram_enabled: true,
      discord_enabled: true,
      telegram_onsnatch: false,
      discord_onsnatch: false,
    } as SettingsFormData;
    const config = {
      telegram_enabled: true,
      discord_enabled: true,
    } as ReadableConfig;

    const { container } = render(
      <NotificationsTab
        config={config}
        formData={formData}
        onChange={onChange}
      />,
    );

    const ids = [...container.querySelectorAll("[id]")]
      .map((el) => el.id)
      .filter(Boolean);
    expect(new Set(ids).size).toBe(ids.length);

    const snatchLabels = screen.getAllByText("Notify on snatch");
    expect(snatchLabels.length).toBeGreaterThanOrEqual(2);
    await user.click(snatchLabels[1]);

    expect(onChange).toHaveBeenCalledWith("discord_onsnatch", true);
    expect(onChange).not.toHaveBeenCalledWith("telegram_onsnatch", true);
  });
});
