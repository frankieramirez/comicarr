import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen } from "../test-utils";
import WantedPacingBanner from "@/components/queue/WantedPacingBanner";
import { approxDuration, untilLabel } from "@/lib/wantedPacing";
import type { WantedPacing } from "@/types";

const pacing: WantedPacing = {
  state: "checking",
  total: 13374,
  checked: 4000,
  waiting: 9374,
  per_hour: 612,
  measured: true,
  per_pass: 250,
  interval_minutes: 20,
  finishes_in_hours: 15.4,
  next_pass_at: new Date(Date.now() + 18 * 60_000 + 5_000).toISOString(),
  new_issue_days: 14,
  search_interval_minutes: 1440,
  next_search_at: null,
  indexers: 13,
};

describe("Wanted pacing", () => {
  it("words durations the way the design does", () => {
    expect(approxDuration(0.3)).toBe("~18 min");
    expect(approxDuration(5.2)).toBe("~5 hours");
    expect(approxDuration(24 * 14)).toBe("~14 days");
    expect(untilLabel(null)).toBeNull();
    expect(
      untilLabel("2026-01-01T00:20:00Z", Date.parse("2026-01-01T00:00:00Z")),
    ).toBe("in 20 min");
  });

  it("says how fast the backlog is checked and when it finishes", async () => {
    const onSearchNow = vi.fn();
    const user = userEvent.setup();
    render(<WantedPacingBanner pacing={pacing} onSearchNow={onSearchNow} />);

    const banner = screen.getByTestId("wanted-pacing");
    expect(banner.textContent).toContain(
      "Auto-search is checking the backlog at 612 an hour",
    );
    expect(banner.textContent).toContain("your 13 indexers every day");
    expect(banner.textContent).toContain("Next batch in 18 min");
    expect(banner.textContent).toContain("~15 hours");
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe(
      "4000",
    );
    await user.click(screen.getByRole("button", { name: "Search now…" }));
    expect(onSearchNow).toHaveBeenCalledOnce();
  });

  it("explains when backlog checks are off and hides when nothing is wanted", () => {
    const { rerender } = render(
      <WantedPacingBanner pacing={{ ...pacing, state: "off", per_hour: 0 }} />,
    );
    expect(screen.getByText("Backlog checks are off")).toBeTruthy();
    expect(screen.queryByRole("progressbar")).toBeNull();
    rerender(<WantedPacingBanner pacing={{ ...pacing, state: "idle" }} />);
    expect(screen.queryByTestId("wanted-pacing")).toBeNull();
  });
});
