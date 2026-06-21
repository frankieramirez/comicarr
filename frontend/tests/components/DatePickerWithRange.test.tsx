import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { screen, renderMinimal, waitFor } from "../test-utils";
import { DatePickerWithRange } from "@/components/custom/date-picker-with-range";
import type { DateRange } from "react-day-picker";

function DatePickerHarness() {
  const [date, setDate] = useState<DateRange | undefined>();

  return <DatePickerWithRange date={date} setDate={setDate} />;
}

describe("DatePickerWithRange", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "ResizeObserver",
      class ResizeObserver {
        observe = vi.fn();
        unobserve = vi.fn();
        disconnect = vi.fn();
      },
    );
  });

  it("opens the calendar and autofocuses a day button", async () => {
    renderMinimal(<DatePickerHarness />);

    await userEvent.click(screen.getByRole("button", { name: /pick a date/i }));

    await waitFor(() => {
      expect(
        document.activeElement instanceof HTMLButtonElement &&
          document.activeElement.hasAttribute("data-day"),
      ).toBe(true);
    });
  });
});
