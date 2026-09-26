import { createElement, useState } from "react";
import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen } from "../test-utils";
import { SearchTab } from "@/components/settings/SearchTab";
import type { WritableConfig } from "@/types/config.generated";

function DelayHarness() {
  const [delay, setDelay] = useState(60);
  return createElement(SearchTab, {
    config: {},
    formData: { search_delay: delay },
    onChange: (key: keyof WritableConfig, value: number | string | boolean) => {
      if (key === "search_delay") setDelay(value as number);
    },
  });
}

describe("Search settings delay", () => {
  it("shows the provider pause in seconds and saves a shorter value", async () => {
    const user = userEvent.setup();

    render(createElement(DelayHarness));

    const field = screen.getByLabelText("Search delay (seconds)");
    expect((field as HTMLInputElement).value).toBe("60");
    expect((field as HTMLInputElement).min).toBe("5");

    await user.tripleClick(field);
    await user.keyboard("12");

    expect((field as HTMLInputElement).value).toBe("12");
  });
});
